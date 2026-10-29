// Register PWA Service Worker
if ('serviceWorker' in navigator) {
  const hadServiceWorker = Boolean(navigator.serviceWorker.controller);
  let isReloadingForSwUpdate = false;

  // Pick up a new SW immediately and reload once it takes control
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!hadServiceWorker || isReloadingForSwUpdate) return;
    isReloadingForSwUpdate = true;
    window.location.reload();
  });

  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js', { updateViaCache: 'none' })
      .then((reg) => {
        reg.update();
        console.log('Locus SW registered:', reg.scope);
      })
      .catch((err) => console.log('Locus SW registration failed:', err));
  });
}

// Modal helpers with smooth fade transitions
let modalCloseTimeout = null;
let modalScrollY = window.scrollY;

// Mobile bottom-sheet: swipe down on the sheet to dismiss it.
function bindSheetSwipe(modal) {
  const sheet = modal.lastElementChild;
  if (!sheet || sheet.dataset.sheetSwipeBound === '1') return;
  sheet.dataset.sheetSwipeBound = '1';

  let startY = 0;
  let startX = 0;
  let dragY = 0;
  let dragging = false;
  let decided = false;

  const backdrop = () => modal.firstElementChild;
  const threshold = () => Math.min(sheet.offsetHeight * 0.25, 120);

  const resetStyles = () => {
    sheet.style.transition = '';
    sheet.style.transform = '';
    const bd = backdrop();
    if (bd) bd.style.opacity = '';
  };

  const canStartDrag = (target) => {
    if (window.innerWidth >= 768) return false;
    if (!target || !sheet.contains(target)) return false;

    // Never hijack gestures that start on interactive controls
    const tag = (target.tagName || '').toUpperCase();
    if (['INPUT', 'TEXTAREA', 'SELECT', 'OPTION', 'BUTTON', 'A', 'LABEL'].includes(tag)) return false;

    // If inner content is scrolled, let it scroll back up first
    const scroller = target.closest('.overflow-y-auto');
    if (scroller && scroller.scrollTop > 0) return false;

    return true;
  };

  const startDrag = (x, y) => {
    startY = y;
    startX = x;
    dragY = 0;
    dragging = true;
    decided = false;
    sheet.style.transition = 'none';
  };

  const moveDrag = (x, y, evt) => {
    if (!dragging) return;

    const dy = y - startY;
    const dx = x - startX;

    if (!decided) {
      // Mostly horizontal gesture: let the page handle it (week swipe etc.)
      if (Math.abs(dx) > Math.abs(dy) * 1.2) {
        dragging = false;
        resetStyles();
        return;
      }
      if (Math.abs(dy) < 3) return;
      decided = true;
    }

    // Dragging upwards: leave native scrolling alone
    if (dy <= 0) {
      dragY = 0;
      sheet.style.transform = '';
      return;
    }

    // Block native scrolling early so iOS does not steal the gesture
    if (evt && evt.cancelable) evt.preventDefault();
    dragY = dy;
    sheet.style.transform = `translateY(${dy}px)`;
    const bd = backdrop();
    if (bd) {
      bd.style.opacity = String(Math.max(0.2, 1 - dy / (sheet.offsetHeight * 1.4)));
    }
  };

  const endDrag = (cancelled) => {
    if (!dragging) return;
    dragging = false;

    const shouldClose = !cancelled && decided && dragY > threshold();
    dragY = 0;
    decided = false;

    if (!shouldClose) {
      // Spring back to the open position
      resetStyles();
      return;
    }

    // Continue moving downwards from the current finger position, then hide
    sheet.style.transition = 'transform 0.22s cubic-bezier(0.4, 0, 1, 1), opacity 0.22s ease-out';
    void sheet.offsetHeight; // commit the current drag offset before animating
    sheet.style.transform = 'translateY(100%)';
    const bd = backdrop();
    if (bd) bd.style.opacity = '0';
    closeModal(modal.id);
  };

  // Touch gestures (real phones, iOS PWA)
  sheet.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 1 || dragging) return;
    if (!canStartDrag(e.target)) return;
    startDrag(e.touches[0].clientX, e.touches[0].clientY);
  }, { passive: true });

  sheet.addEventListener('touchmove', (e) => {
    if (!dragging || e.touches.length !== 1) return;
    moveDrag(e.touches[0].clientX, e.touches[0].clientY, e);
  }, { passive: false });

  sheet.addEventListener('touchend', () => endDrag(false), { passive: true });
  sheet.addEventListener('touchcancel', () => endDrag(true), { passive: true });

  // Mouse drag for desktop responsive mode / devtools device toolbar
  sheet.addEventListener('mousedown', (e) => {
    if (e.button !== 0 || dragging) return;
    if (window.getSelection && String(window.getSelection())) return;
    if (!canStartDrag(e.target)) return;
    e.preventDefault();
    startDrag(e.clientX, e.clientY);
  });

  window.addEventListener('mousemove', (e) => {
    if (dragging) moveDrag(e.clientX, e.clientY, null);
  });

  window.addEventListener('mouseup', () => {
    if (dragging) endDrag(false);
  });
}

function openModal(id) {
  if (modalCloseTimeout) {
    clearTimeout(modalCloseTimeout);
    modalCloseTimeout = null;
  }
  const modal = document.getElementById(id);
  if (modal) {
    // Remember where the page was before the first modal opens, so iOS
    // keyboard scroll-into-view does not leave the page shifted down.
    // Ignore the modal being opened: the dashboard lesson modal is injected
    // by HTMX already visible, and would otherwise be mistaken for another one.
    const anotherModalOpen = Array.from(
      document.querySelectorAll('[data-modal].flex:not(.hidden)')
    ).some((openModalEl) => openModalEl !== modal);
    if (!anotherModalOpen) {
      modalScrollY = window.scrollY;
    }
    bindSheetSwipe(modal);
    if (id === 'add-hw-modal') {
      maybeAutoApplyNextLesson(modal);
    }
    syncDateDisplays(modal);
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    requestAnimationFrame(() => {
      if (!modal.classList.contains('hidden')) {
        modal.classList.add('modal-visible');
      }
    });
    document.body.style.overflow = 'hidden';
  }
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (modal) {
    // Drop keyboard focus before hiding: iOS otherwise keeps scrolling the
    // page back to the (now invisible) focused field.
    if (modal.contains(document.activeElement) && document.activeElement.blur) {
      document.activeElement.blur();
    }
    modal.classList.remove('modal-visible');
    if (modalCloseTimeout) {
      clearTimeout(modalCloseTimeout);
    }
    modalCloseTimeout = setTimeout(() => {
      if (!modal.classList.contains('modal-visible')) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        // Drop inline drag styles left over from swipe-to-dismiss
        const sheet = modal.lastElementChild;
        if (sheet) {
          sheet.style.transition = '';
          sheet.style.transform = '';
        }
        const backdrop = modal.firstElementChild;
        if (backdrop) backdrop.style.opacity = '';
        if (!document.querySelector('[data-modal]:not(.hidden)')) {
          document.body.style.overflow = '';
          window.scrollTo({ top: modalScrollY, behavior: 'instant' });
        }
        if (id === 'lesson-detail-modal') {
          const container = document.getElementById('lesson-modal-container');
          if (container) container.innerHTML = '';
        }
      }
      modalCloseTimeout = null;
    }, 260);
  }
}

// Tap-press feedback for lesson cards and homework checkboxes.
// CSS :active is unreliable on iOS and flashes too briefly, so the pressed
// state is driven by pointer events and stays visible for a minimum time.
const PRESS_MIN_DURATION = 160;
const pressStartedAt = new WeakMap();
const pressTimers = new WeakMap();
const pressedElements = new Set();

function startPress(el) {
  const timer = pressTimers.get(el);
  if (timer) {
    clearTimeout(timer);
    pressTimers.delete(el);
  }
  pressStartedAt.set(el, Date.now());
  el.classList.add('is-pressing');
  pressedElements.add(el);
}

function endPress(el) {
  const startedAt = pressStartedAt.get(el) || Date.now();
  const delay = Math.max(0, PRESS_MIN_DURATION - (Date.now() - startedAt));
  pressTimers.set(el, setTimeout(() => {
    el.classList.remove('is-pressing');
    pressTimers.delete(el);
  }, delay));
}

document.addEventListener('pointerdown', (e) => {
  const toggle = e.target.closest('[data-hw-toggle]');
  if (toggle) {
    startPress(toggle);
    return;
  }

  const card = e.target.closest('[data-pressable-card]');
  if (!card) return;
  if (e.target.closest('button, a, input, select, textarea, label')) return;
  startPress(card);
}, { passive: true });

function releasePresses() {
  pressedElements.forEach((el) => endPress(el));
  pressedElements.clear();
}

document.addEventListener('pointerup', releasePresses, { passive: true });
document.addEventListener('pointercancel', releasePresses, { passive: true });

// Close modals when clicking escape
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('[data-modal]').forEach((modal) => {
      if (!modal.classList.contains('hidden')) {
        closeModal(modal.id);
      }
    });
  }
});

// Prepare modals (bottom-sheet gestures + auto-open state)
function initModals() {
  const autoOpenModal = document.querySelector('[data-modal].flex:not(.hidden)');
  if (autoOpenModal) {
    modalScrollY = window.scrollY;
  }
  document.querySelectorAll('[data-modal]').forEach((modal) => {
    bindSheetSwipe(modal);
  });
  if (autoOpenModal) {
    maybeAutoApplyNextLesson(autoOpenModal);
  }
  syncDateDisplays();
  document.querySelectorAll('[data-modal].flex').forEach((modal) => {
    requestAnimationFrame(() => {
      if (!modal.classList.contains('hidden')) {
        modal.classList.add('modal-visible');
      }
    });
    document.body.style.overflow = 'hidden';
  });
}

// Close modal when clicking on backdrop container
document.addEventListener('click', (e) => {
  if (e.target && e.target.hasAttribute('data-modal')) {
    closeModal(e.target.id);
  }
});

// ============================================================
// Client-side section navigation (Dock + Sidebar)
// Pages fade into each other instead of doing a full reload.
// ============================================================
let isNavigatingPage = false;
let lastPagePath = window.location.pathname;
let lastPageUrl = window.location.pathname + window.location.search;
const SECTION_PATHS = new Set(['/', '/homework', '/subjects', '/schedule', '/admin/users']);

// Inline <script> tags inserted via innerHTML never run, so re-create them
function runScripts(container) {
  container.querySelectorAll('script').forEach((oldScript) => {
    const script = document.createElement('script');
    Array.from(oldScript.attributes).forEach((attr) => script.setAttribute(attr.name, attr.value));
    script.textContent = oldScript.textContent;
    oldScript.replaceWith(script);
  });
}

// Instantly dismiss any open modal/menu before swapping the page
function hideOpenOverlays() {
  if (document.activeElement && document.activeElement.blur) {
    document.activeElement.blur();
  }
  document.querySelectorAll('[data-modal]:not(.hidden)').forEach((modal) => {
    modal.classList.remove('modal-visible');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  });
  document.body.style.overflow = '';
}

// iOS renders <input type="date"> with a localized, oversized native label
// ("23 окт. 2026 г."). Show a consistent DD.MM.YYYY value above it instead,
// while keeping the native date picker for taps.
function formatDisplayDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
  return match ? `${match[3]}.${match[2]}.${match[1]}` : '';
}

function syncDateDisplays(root = document) {
  const scope = root && root.querySelectorAll ? root : document;
  scope.querySelectorAll('.hw-date-input').forEach((input) => {
    const display = input.parentElement
      ? input.parentElement.querySelector('.hw-date-display')
      : null;
    if (display) display.textContent = formatDisplayDate(input.value);
  });
}

function updateHwModalSubgroupVisibility(modal) {
  const modalEl = modal || document.getElementById('add-hw-modal');
  if (!modalEl) return;
  const subjectSelect = modalEl.querySelector('#subject_id');
  const subgroupContainer = modalEl.querySelector('#hw-subgroup-field-container');
  const subgroupSelect = modalEl.querySelector('#hw_subgroup');
  if (!subjectSelect || !subgroupContainer || !subgroupSelect) return;

  const selectedOpt = subjectSelect.options[subjectSelect.selectedIndex];
  const hasSubgroups = selectedOpt && selectedOpt.getAttribute('data-has-subgroups') === 'true';

  if (!hasSubgroups) {
    subgroupContainer.classList.add('hidden');
    subgroupSelect.value = '';
    subgroupSelect.disabled = true;
  } else {
    subgroupContainer.classList.remove('hidden');
    subgroupSelect.disabled = false;
    if (!subgroupSelect.value) {
      const userSubgroup = subgroupSelect.getAttribute('data-user-subgroup');
      if (userSubgroup) {
        subgroupSelect.value = userSubgroup;
      }
    }
  }
}

function applyNextLessonSuggestion(modal) {
  const button = modal ? modal.querySelector('[data-next-lesson-btn]') : null;
  if (!button) return false;

  const subjectId = button.getAttribute('data-subject-id');
  const lessonId = button.getAttribute('data-lesson-id');
  const dueDate = button.getAttribute('data-due-date');
  const subgroup = button.getAttribute('data-subgroup');
  const subjectSelect = modal.querySelector('#subject_id');
  const dueInput = modal.querySelector('#due_date');
  const subgroupSelect = modal.querySelector('#hw_subgroup') || modal.querySelector('#subgroup');

  if (subjectSelect && subjectId) {
    subjectSelect.value = subjectId;
    updateHwModalSubgroupVisibility(modal);
  }
  if (dueInput && dueDate) dueInput.value = dueDate;
  if (subgroupSelect) {
    const targetSubgroup = (subgroup !== null && subgroup !== undefined) ? String(subgroup) : '';
    subgroupSelect.value = targetSubgroup;
  }

  // Link the task to the next occurrence of the subject so paired lessons
  // show it in the correct card.
  const lessonInput = modal.querySelector('#hw_lesson_id');
  if (lessonInput) lessonInput.value = lessonId ? String(lessonId) : '';

  syncDateDisplays(modal);
  return true;
}

function maybeAutoApplyNextLesson(modal) {
  if (!modal || modal.id !== 'add-hw-modal') return;

  if (modal.dataset.skipNextLessonAuto === '1') {
    delete modal.dataset.skipNextLessonAuto;
    return;
  }

  const button = modal.querySelector('[data-next-lesson-btn]');
  if (button && button.getAttribute('data-auto-apply') === 'true') {
    applyNextLessonSuggestion(modal);
  } else {
    updateHwModalSubgroupVisibility(modal);
  }
}

document.addEventListener('click', (e) => {
  const button = e.target.closest ? e.target.closest('[data-next-lesson-btn]') : null;
  if (!button) return;

  const modal = button.closest('#add-hw-modal');
  if (!modal) return;

  e.preventDefault();
  applyNextLessonSuggestion(modal);
  button.style.borderColor = 'rgba(16, 185, 129, 0.7)';
  setTimeout(() => {
    button.style.borderColor = '';
  }, 450);
});

// Changing the subject or date manually breaks the link to a lesson that was
// preselected from a specific lesson card.
document.addEventListener('change', (e) => {
  const target = e.target;
  if (!target || !target.closest) return;

  const modal = target.closest('#add-hw-modal');
  if (!modal) return;

  if (target.id === 'subject_id') {
    updateHwModalSubgroupVisibility(modal);
  }

  if (target.id !== 'subject_id' && target.id !== 'due_date' && target.id !== 'hw_subgroup') return;

  const lessonInput = modal.querySelector('#hw_lesson_id');
  if (lessonInput) lessonInput.value = '';
});

let lastAlertedSundayValue = null;
function handleDateInput(event) {
  const input = event.target;
  if (input && input.classList && input.classList.contains('hw-date-input')) {
    if (input.value) {
      const parts = input.value.split('-');
      if (parts.length === 3) {
        const d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        if (d.getDay() === 0) {
          if (lastAlertedSundayValue !== input.value) {
            lastAlertedSundayValue = input.value;
            alert('Нельзя записать домашнее задание на воскресенье');
            setTimeout(() => { lastAlertedSundayValue = null; }, 500);
          }
          d.setDate(d.getDate() + 1);
          const y = d.getFullYear();
          const m = String(d.getMonth() + 1).padStart(2, '0');
          const day = String(d.getDate()).padStart(2, '0');
          input.value = `${y}-${m}-${day}`;
          const modal = input.closest('#add-hw-modal');
          if (modal) {
            const lessonInput = modal.querySelector('#hw_lesson_id');
            if (lessonInput) lessonInput.value = '';
          }
        }
      }
    }
    syncDateDisplays(input.parentElement);
  }
}

document.addEventListener('input', handleDateInput);
document.addEventListener('change', handleDateInput);

// Highlight the dock button immediately, before the new page arrives
function setDockActive(pathname) {
  const activeClasses = ['bg-emerald-500', 'text-white', 'shadow-md', 'shadow-emerald-500/25', 'font-bold', 'is-active'];
  const idleClasses = ['text-zinc-400', 'hover:text-white', 'bg-transparent'];

  document.querySelectorAll('#mobile-bottom-nav a[data-dock-tab]').forEach((link) => {
    const linkPath = new URL(link.href, window.location.origin).pathname;
    const isActive = linkPath === pathname;
    activeClasses.forEach((cls) => link.classList.toggle(cls, isActive));
    idleClasses.forEach((cls) => link.classList.toggle(cls, !isActive));
  });
}

// Keep navigation chrome (sidebar / dock active states / mobile menu) in sync
function syncNavigationState(doc) {
  const newAside = doc.querySelector('aside');
  const curAside = document.querySelector('aside');
  if (newAside && curAside) {
    curAside.innerHTML = newAside.innerHTML;
  }

  const newDock = doc.getElementById('mobile-bottom-nav');
  const curDock = document.getElementById('mobile-bottom-nav');
  if (newDock && curDock) {
    curDock.innerHTML = newDock.innerHTML;
  }

  const newMobileMenu = doc.getElementById('mobile-menu-modal');
  const curMobileMenu = document.getElementById('mobile-menu-modal');
  if (newMobileMenu && curMobileMenu) {
    curMobileMenu.innerHTML = newMobileMenu.innerHTML;
  }
}

// Remember the selected dashboard date across section switches
const SELECTED_DATE_KEY = 'locus:selected-date';

function readSelectedDate() {
  try {
    return sessionStorage.getItem(SELECTED_DATE_KEY) || '';
  } catch (e) {
    return '';
  }
}

function writeSelectedDate(date) {
  try {
    if (date) {
      sessionStorage.setItem(SELECTED_DATE_KEY, date);
    } else {
      sessionStorage.removeItem(SELECTED_DATE_KEY);
    }
  } catch (e) {
    // Storage may be unavailable — links then fall back to the current week
  }
}

function dashboardHref() {
  if (window.location.pathname === '/') {
    const date = new URLSearchParams(window.location.search).get('date');
    writeSelectedDate(date || '');
    return date ? `/?date=${encodeURIComponent(date)}` : '/';
  }

  const saved = readSelectedDate();
  return saved ? `/?date=${encodeURIComponent(saved)}` : '/';
}

// Point the sidebar/dock "Дневник" links at the week the user last opened
function syncDashboardLinks() {
  const href = dashboardHref();
  document.querySelectorAll('[data-nav-dashboard]').forEach((link) => {
    link.setAttribute('href', href);
  });
}

async function navigateToPage(targetUrl, push = true) {
  if (isNavigatingPage) return false;

  const main = document.querySelector('main');
  if (!main) {
    window.location.href = targetUrl;
    return false;
  }

  isNavigatingPage = true;

  const targetURL = new URL(targetUrl, window.location.href);
  const targetPath = targetURL.pathname;
  const targetUrlKey = targetURL.pathname + targetURL.search;
  const outClass = 'anim-page-fade-out';
  const inClass = 'anim-page-fade-in';

  setDockActive(targetPath);
  hideOpenOverlays();

  try {
    const fetchPromise = fetch(targetUrl, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });

    main.classList.remove('anim-page-fade-in', 'anim-page-fade-out');
    void main.offsetWidth; // Force reflow
    main.classList.add(outClass);

    const [res] = await Promise.all([
      fetchPromise,
      new Promise((resolve) => setTimeout(resolve, 140))
    ]);

    if (!res.ok) {
      throw new Error(`HTTP error ${res.status}`);
    }

    const html = await res.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const newMain = doc.querySelector('main');

    // Auth redirects and unexpected responses keep the classic navigation
    if (!newMain || !doc.getElementById('mobile-bottom-nav')) {
      throw new Error('Unexpected page structure');
    }

    // Swap content, keeping page-specific <main> classes (padding)
    main.className = newMain.className.replace(/\banimate-fade-in\b/g, '').trim();
    main.innerHTML = newMain.innerHTML;
    runScripts(main);

    const newModals = doc.getElementById('page-modals');
    const curModals = document.getElementById('page-modals');
    if (newModals && curModals) {
      curModals.innerHTML = newModals.innerHTML;
      runScripts(curModals);
    }

    syncNavigationState(doc);

    if (doc.title) {
      document.title = doc.title;
    }

    lastPagePath = targetPath;
    lastPageUrl = targetUrlKey;
    window.scrollTo({ top: 0, behavior: 'instant' });

    if (push) {
      window.history.pushState({ locusPageUrl: targetUrl }, '', targetUrl);
    }

    if (window.htmx) {
      window.htmx.process(main);
      if (curModals) window.htmx.process(curModals);
    }

    initModals();

    // Seamless out -> in transition without an intermediate unstyled frame
    main.classList.remove(outClass);
    main.classList.add(inClass);

    initPageBehaviour();

    setTimeout(() => {
      main.classList.remove(inClass);
      isNavigatingPage = false;
    }, 200);

    return true;
  } catch (err) {
    console.warn('Page switch fetch error, falling back to full navigation:', err);
    main.classList.remove(outClass, inClass);
    isNavigatingPage = false;
    window.location.href = targetUrl;
    return false;
  }
}

// Desktop dashboard: fade only the day content, keep the week/day selector still
let isSwitchingDashboardDate = false;

async function navigateDashboardDate(targetUrl, push = true) {
  if (isSwitchingDashboardDate) return false;

  const selector = document.getElementById('desktop-week-selector');
  const content = document.getElementById('desktop-dashboard-content');
  if (!selector || !content) {
    window.location.href = targetUrl;
    return false;
  }

  const targetURL = new URL(targetUrl, window.location.href);
  const targetUrlKey = targetURL.pathname + targetURL.search;
  const outClass = 'anim-page-fade-out';
  const inClass = 'anim-page-fade-in';

  isSwitchingDashboardDate = true;

  try {
    const fetchPromise = fetch(targetUrl, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });

    content.classList.remove('anim-page-fade-in', 'anim-page-fade-out');
    void content.offsetWidth; // Force reflow
    content.classList.add(outClass);

    const [res] = await Promise.all([
      fetchPromise,
      new Promise((resolve) => setTimeout(resolve, 140))
    ]);

    if (!res.ok) {
      throw new Error(`HTTP error ${res.status}`);
    }

    const html = await res.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const newView = doc.getElementById('desktop-dashboard-view');
    const newSelector = doc.getElementById('desktop-week-selector');
    const newContent = doc.getElementById('desktop-dashboard-content');

    if (!newView || !newSelector || !newContent) {
      throw new Error('Unexpected dashboard structure');
    }

    // The selector snaps to the new active day without fading
    selector.innerHTML = newSelector.innerHTML;
    content.innerHTML = newContent.innerHTML;

    const currentView = document.getElementById('desktop-dashboard-view');
    if (currentView && newView.hasAttribute('data-is-today')) {
      currentView.setAttribute('data-is-today', newView.getAttribute('data-is-today'));
    }

    // Keep the hidden mobile view in sync for responsive resizing
    const newMobile = doc.getElementById('mobile-week-view');
    const currentMobile = document.getElementById('mobile-week-view');
    if (newMobile && currentMobile) {
      currentMobile.innerHTML = newMobile.innerHTML;
      ['data-is-current-week', 'data-today-day-num'].forEach((attr) => {
        if (newMobile.hasAttribute(attr)) {
          currentMobile.setAttribute(attr, newMobile.getAttribute(attr));
        }
      });
    }

    // Keep the quick-add modal pointed at the selected day
    const newDue = doc.getElementById('due_date');
    const currentDue = document.getElementById('due_date');
    if (newDue && currentDue) currentDue.value = newDue.value;

    const newReturnUrl = doc.querySelector('#add-hw-modal input[name="return_url"]');
    const currentReturnUrl = document.querySelector('#add-hw-modal input[name="return_url"]');
    if (newReturnUrl && currentReturnUrl) {
      currentReturnUrl.value = newReturnUrl.value;
    }

    lastPagePath = targetURL.pathname;
    lastPageUrl = targetUrlKey;

    if (push) {
      window.history.pushState({ locusDateUrl: targetUrl }, '', targetUrl);
    }
    if (doc.title) {
      document.title = doc.title;
    }

    syncDashboardLinks();
    syncDateDisplays();

    if (window.htmx) {
      window.htmx.process(content);
      if (currentMobile) window.htmx.process(currentMobile);
    }

    updateCurrentLessonBadges();

    content.classList.remove(outClass);
    content.classList.add(inClass);

    setTimeout(() => {
      content.classList.remove(inClass);
      isSwitchingDashboardDate = false;
    }, 200);

    return true;
  } catch (err) {
    console.warn('Dashboard date switch failed, falling back to full navigation:', err);
    content.classList.remove(outClass, inClass);
    isSwitchingDashboardDate = false;
    window.location.href = targetUrl;
    return false;
  }
}

// Intercept section links in the dock, sidebar and mobile menu
document.addEventListener('click', (e) => {
  if (e.defaultPrevented || e.button !== 0) return;
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

  const target = e.target;
  const link = target && target.closest ? target.closest('a[href]') : null;
  if (!link) return;
  if (link.target && link.target !== '_self') return;
  if (link.hasAttribute('download')) return;
  if (!link.closest('#mobile-bottom-nav, aside, #mobile-menu-modal')) return;

  const url = new URL(link.href, window.location.href);
  if (url.origin !== window.location.origin) return;
  if (!SECTION_PATHS.has(url.pathname)) return;

  e.preventDefault();

  // Re-tapping the current section just closes an open menu
  if (url.pathname === window.location.pathname && url.search === window.location.search) {
    hideOpenOverlays();
    return;
  }

  navigateToPage(url.pathname + url.search);
});

// Desktop dashboard: fade between days/weeks instead of a full reload
document.addEventListener('click', (e) => {
  if (e.defaultPrevented || e.button !== 0) return;
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

  const target = e.target;
  const link = target && target.closest ? target.closest('a[data-date-nav]') : null;
  if (!link) return;
  if (link.target && link.target !== '_self') return;
  if (link.hasAttribute('download')) return;

  const url = new URL(link.href, window.location.href);
  if (url.origin !== window.location.origin || url.pathname !== '/') return;

  // The mobile week view keeps its slide animation
  if (window.innerWidth < 768) return;

  e.preventDefault();

  if (url.pathname === window.location.pathname && url.search === window.location.search) {
    hideOpenOverlays();
    return;
  }

  navigateDashboardDate(url.pathname + url.search);
});

// Homework filters: fade only the task list, keeping the header and tabs still
let isSwitchingHomeworkFilter = false;

async function navigateHomeworkFilter(targetUrl, push = true) {
  if (isSwitchingHomeworkFilter) return false;

  const container = document.getElementById('hw-container');
  const filters = document.getElementById('hw-filters');
  if (!container || !filters) {
    window.location.href = targetUrl;
    return false;
  }

  const targetURL = new URL(targetUrl, window.location.href);
  const targetUrlKey = targetURL.pathname + targetURL.search;
  const outClass = 'anim-page-fade-out';
  const inClass = 'anim-page-fade-in';

  isSwitchingHomeworkFilter = true;

  try {
    const fetchPromise = fetch(targetUrl, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });

    container.classList.remove('anim-page-fade-in', 'anim-page-fade-out');
    void container.offsetWidth; // Force reflow
    container.classList.add(outClass);

    const [res] = await Promise.all([
      fetchPromise,
      new Promise((resolve) => setTimeout(resolve, 140))
    ]);

    if (!res.ok) {
      throw new Error(`HTTP error ${res.status}`);
    }

    const html = await res.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const newContainer = doc.getElementById('hw-container');
    const newFilters = doc.getElementById('hw-filters');
    const newSubgroupFilters = doc.getElementById('hw-subgroup-filters');
    const curSubgroupFilters = document.getElementById('hw-subgroup-filters');

    if (!newContainer || !newFilters) {
      throw new Error('Unexpected homework page structure');
    }

    // Swap just the list, filter tabs, and subgroup filter buttons
    container.innerHTML = newContainer.innerHTML;
    filters.innerHTML = newFilters.innerHTML;
    if (newSubgroupFilters && curSubgroupFilters) {
      curSubgroupFilters.innerHTML = newSubgroupFilters.innerHTML;
    }

    lastPagePath = targetURL.pathname;
    lastPageUrl = targetUrlKey;

    if (push) {
      window.history.pushState({ locusPageUrl: targetUrl }, '', targetUrl);
    }

    if (window.htmx) {
      window.htmx.process(container);
    }

    container.classList.remove(outClass);
    container.classList.add(inClass);

    setTimeout(() => {
      container.classList.remove(inClass);
      isSwitchingHomeworkFilter = false;
    }, 200);

    return true;
  } catch (err) {
    console.warn('Homework filter switch failed, falling back to full navigation:', err);
    container.classList.remove(outClass, inClass);
    isSwitchingHomeworkFilter = false;
    window.location.href = targetUrl;
    return false;
  }
}

// Homework filter tabs: fade between lists instead of a full reload
document.addEventListener('click', (e) => {
  if (e.defaultPrevented || e.button !== 0) return;
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

  const target = e.target;
  const link = target && target.closest ? target.closest('a[data-hw-filter]') : null;
  if (!link) return;
  if (link.target && link.target !== '_self') return;
  if (link.hasAttribute('download')) return;

  const url = new URL(link.href, window.location.href);
  if (url.origin !== window.location.origin || url.pathname !== '/homework') return;

  e.preventDefault();

  if (url.pathname === window.location.pathname && url.search === window.location.search) {
    hideOpenOverlays();
    return;
  }

  navigateHomeworkFilter(url.pathname + url.search);
});

// Mobile dashboard subgroup switcher with smooth fade
let isSwitchingMobileSubgroup = false;

async function navigateMobileSubgroup(targetUrl, push = true) {
  if (isSwitchingMobileSubgroup) return false;

  const mobileView = document.getElementById('mobile-week-view');
  if (!mobileView) {
    window.location.href = targetUrl;
    return false;
  }

  const targetURL = new URL(targetUrl, window.location.href);
  const targetUrlKey = targetURL.pathname + targetURL.search;
  const outClass = 'anim-page-fade-out';
  const inClass = 'anim-page-fade-in';

  isSwitchingMobileSubgroup = true;

  try {
    const fetchPromise = fetch(targetUrl, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });

    mobileView.classList.remove('anim-page-fade-in', 'anim-page-fade-out', 'anim-week-slide-in-left', 'anim-week-slide-in-right', 'anim-week-slide-out-left', 'anim-week-slide-out-right');
    void mobileView.offsetWidth;
    mobileView.classList.add(outClass);

    const [res] = await Promise.all([
      fetchPromise,
      new Promise((resolve) => setTimeout(resolve, 140))
    ]);

    if (!res.ok) throw new Error(`HTTP error ${res.status}`);

    const html = await res.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const newMobileView = doc.getElementById('mobile-week-view');
    if (!newMobileView) throw new Error('Unexpected mobile view structure');

    const newDesktopView = doc.getElementById('desktop-dashboard-view');
    const curDesktopView = document.getElementById('desktop-dashboard-view');
    if (newDesktopView && curDesktopView) {
      curDesktopView.innerHTML = newDesktopView.innerHTML;
    }

    mobileView.innerHTML = newMobileView.innerHTML;
    if (newMobileView.hasAttribute('data-is-current-week')) {
      mobileView.setAttribute('data-is-current-week', newMobileView.getAttribute('data-is-current-week'));
    }
    if (newMobileView.hasAttribute('data-today-day-num')) {
      mobileView.setAttribute('data-today-day-num', newMobileView.getAttribute('data-today-day-num'));
    }

    lastPagePath = targetURL.pathname;
    lastPageUrl = targetUrlKey;

    if (push) {
      window.history.pushState({ locusDateUrl: targetUrl }, '', targetUrl);
    }
    if (doc.title) {
      document.title = doc.title;
    }

    syncDashboardLinks();

    if (window.htmx) {
      window.htmx.process(mobileView);
      if (curDesktopView) {
        window.htmx.process(curDesktopView);
      }
    }

    initMobileWeekScrollSpy();
    updateCurrentLessonBadges();

    mobileView.classList.remove(outClass);
    mobileView.classList.add(inClass);

    setTimeout(() => {
      mobileView.classList.remove(inClass);
      isSwitchingMobileSubgroup = false;
    }, 200);

    return true;
  } catch (err) {
    console.warn('Mobile subgroup switch failed, falling back to full navigation:', err);
    mobileView.classList.remove(outClass, inClass);
    isSwitchingMobileSubgroup = false;
    window.location.href = targetUrl;
    return false;
  }
}

// Subgroup filter buttons on dashboard and homework pages
document.addEventListener('click', (e) => {
  if (e.defaultPrevented || e.button !== 0) return;
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

  const target = e.target;
  const link = target && target.closest ? target.closest('a[data-subgroup-filter]') : null;
  if (!link) return;
  if (link.target && link.target !== '_self') return;
  if (link.hasAttribute('download')) return;

  const url = new URL(link.href, window.location.href);
  if (url.origin !== window.location.origin) return;

  e.preventDefault();

  if (url.pathname === window.location.pathname && url.search === window.location.search) {
    hideOpenOverlays();
    return;
  }

  if (url.pathname === '/homework') {
    navigateHomeworkFilter(url.pathname + url.search);
  } else if (url.pathname === '/') {
    if (window.innerWidth < 768) {
      navigateMobileSubgroup(url.pathname + url.search);
    } else {
      navigateDashboardDate(url.pathname + url.search);
    }
  } else {
    navigateToPage(url.pathname + url.search);
  }
});

// Browser Back/Forward: page switch, or week switch while on the dashboard
window.addEventListener('popstate', () => {
  const targetPath = window.location.pathname;
  const targetUrl = targetPath + window.location.search;

  if (targetPath === '/' && lastPagePath === '/' && window.innerWidth < 768) {
    navigateMobileSubgroup(window.location.href, false);
    return;
  }

  if (targetPath === '/' && lastPagePath === '/' && window.innerWidth >= 768) {
    if (targetUrl === lastPageUrl) return;
    navigateDashboardDate(window.location.href, false);
    return;
  }

  if (targetUrl === lastPageUrl) return;

  if (targetPath === '/homework' && lastPagePath === '/homework') {
    navigateHomeworkFilter(window.location.href, false);
    return;
  }

  navigateToPage(window.location.href, false);
});

// Mobile Day Smooth Scroll & Sticky Ribbon Scroll-Spy
let isProgrammaticScroll = false;
let programmaticScrollTimeout = null;
let mobileScrollSpyInitialized = false;

function setActiveMobileDayTab(dayNum) {
  const tabs = document.querySelectorAll('.mobile-day-tab');
  tabs.forEach((tab) => {
    const tabDayNum = tab.getAttribute('data-day-num');
    const badge = tab.querySelector('.day-badge');
    const label = tab.querySelector('.day-label');
    if (badge && label) {
      if (String(tabDayNum) === String(dayNum)) {
        badge.classList.remove('text-zinc-400', 'bg-transparent');
        badge.classList.add('bg-emerald-500', 'text-white', 'shadow-md', 'shadow-emerald-500/25');
        label.classList.remove('text-zinc-500');
        label.classList.add('text-emerald-400');
      } else {
        badge.classList.remove('bg-emerald-500', 'text-white', 'shadow-md', 'shadow-emerald-500/25');
        badge.classList.add('text-zinc-400', 'bg-transparent');
        label.classList.remove('text-emerald-400');
        label.classList.add('text-zinc-500');
      }
    }
  });
}

function scrollToMobileDay(dayNum) {
  // Immediately highlight clicked day tab in emerald green and deselect other tabs
  setActiveMobileDayTab(dayNum);

  // Prevent scroll-spy from overriding the active tab during smooth scroll
  isProgrammaticScroll = true;
  if (programmaticScrollTimeout) clearTimeout(programmaticScrollTimeout);
  programmaticScrollTimeout = setTimeout(() => {
    isProgrammaticScroll = false;
  }, 800);

  const section = document.getElementById('mobile-day-' + dayNum);
  if (section) {
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function updateMobileActiveDayTab() {
  if (isProgrammaticScroll) return;
  const sections = document.querySelectorAll('.mobile-day-section');
  const tabs = document.querySelectorAll('.mobile-day-tab');
  if (!sections.length || !tabs.length) return;

  const scrollPos = window.scrollY + 155;
  let activeDayNum = null;

  for (let i = 0; i < sections.length; i++) {
    const section = sections[i];
    const top = section.offsetTop;
    const height = section.offsetHeight;
    if (scrollPos >= top && scrollPos < top + height) {
      activeDayNum = section.getAttribute('data-day-num');
      break;
    }
  }

  if (!activeDayNum && window.scrollY < 100 && sections.length) {
    activeDayNum = sections[0].getAttribute('data-day-num');
  }

  if (activeDayNum) {
    setActiveMobileDayTab(activeDayNum);
  }
}

function initMobileDayPosition() {
  if (window.innerWidth >= 768) return;
  const mobileView = document.getElementById('mobile-week-view');
  if (!mobileView) return;

  const isCurrentWeek = mobileView.getAttribute('data-is-current-week') === 'true';
  const todayDayNum = mobileView.getAttribute('data-today-day-num');

  // If this is the current week and today is not Monday, smoothly scroll from top down to today
  if (isCurrentWeek && todayDayNum && todayDayNum !== '1' && window.scrollY < 50) {
    const todaySection = document.getElementById('mobile-day-' + todayDayNum);
    if (todaySection) {
      isProgrammaticScroll = true;
      setActiveMobileDayTab(todayDayNum);
      window.scrollTo({ top: 0, behavior: 'instant' });

      setTimeout(() => {
        todaySection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        if (programmaticScrollTimeout) clearTimeout(programmaticScrollTimeout);
        programmaticScrollTimeout = setTimeout(() => {
          isProgrammaticScroll = false;
          updateMobileActiveDayTab();
        }, 850);
      }, 100);
    }
  }
}

function updateCurrentLessonBadges() {
  const now = new Date();
  const currentHours = String(now.getHours()).padStart(2, '0');
  const currentMinutes = String(now.getMinutes()).padStart(2, '0');
  const currentTimeStr = `${currentHours}:${currentMinutes}`;
  const currentIsoDay = now.getDay() === 0 ? 7 : now.getDay();

  function toggleCardNow(card, isNow, isMobile = false) {
    const timeSpan = card.querySelector('.lesson-time-span');
    let nowBadge = card.querySelector('.lesson-now-badge');

    if (isNow) {
      if (isMobile) {
        card.classList.add('border-emerald-500/70', 'shadow-[0_0_20px_rgba(16,185,129,0.2)]');
        card.classList.remove('border-zinc-800/90', 'shadow-[0_4px_20px_rgba(0,0,0,0.85)]', 'hover:border-zinc-700', 'hover:border-emerald-400');
      } else {
        card.classList.add('border-emerald-500/70', 'hover:border-emerald-400', 'shadow-[0_0_20px_rgba(16,185,129,0.2)]', 'hover:shadow-[0_0_25px_rgba(16,185,129,0.35)]');
        card.classList.remove('border-zinc-800/90', 'hover:border-zinc-700', 'shadow-[0_4px_20px_rgba(0,0,0,0.85)]');
      }
      if (timeSpan) {
        timeSpan.classList.add('text-emerald-400', 'font-bold');
        timeSpan.classList.remove('text-zinc-400');
      }
      if (!nowBadge && timeSpan && timeSpan.parentNode) {
        nowBadge = document.createElement('span');
        nowBadge.className = 'lesson-now-badge text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 leading-none';
        nowBadge.textContent = 'Сейчас';
        timeSpan.parentNode.appendChild(nowBadge);
      }
    } else {
      if (isMobile) {
        card.classList.remove('border-emerald-500/70', 'shadow-[0_0_20px_rgba(16,185,129,0.2)]', 'hover:border-emerald-400', 'hover:border-zinc-700');
        card.classList.add('border-zinc-800/90', 'shadow-[0_4px_20px_rgba(0,0,0,0.85)]');
      } else {
        card.classList.remove('border-emerald-500/70', 'hover:border-emerald-400', 'shadow-[0_0_20px_rgba(16,185,129,0.2)]', 'hover:shadow-[0_0_25px_rgba(16,185,129,0.35)]');
        card.classList.add('border-zinc-800/90', 'hover:border-zinc-700', 'shadow-[0_4px_20px_rgba(0,0,0,0.85)]');
      }
      if (timeSpan) {
        timeSpan.classList.remove('text-emerald-400', 'font-bold');
        timeSpan.classList.add('text-zinc-400');
      }
      if (nowBadge) {
        nowBadge.remove();
      }
    }
  }

  // 1. Mobile day sections (only mark lessons as 'now' if current week is displayed)
  const mobileView = document.getElementById('mobile-week-view');
  const isMobileCurrentWeek = mobileView ? (mobileView.getAttribute('data-is-current-week') === 'true') : false;
  const daySections = document.querySelectorAll('.mobile-day-section');
  daySections.forEach((section) => {
    const isToday = isMobileCurrentWeek && (section.getAttribute('data-is-today') === 'true' || String(section.getAttribute('data-day-num')) === String(currentIsoDay));
    const cards = section.querySelectorAll('[data-start-time]');
    cards.forEach((card) => {
      const start = card.getAttribute('data-start-time');
      const end = card.getAttribute('data-end-time');
      const isNow = isToday && Boolean(start && end && start <= currentTimeStr && currentTimeStr <= end);
      toggleCardNow(card, isNow, true);
    });
  });

  // 2. Desktop view cards
  const desktopView = document.getElementById('desktop-dashboard-view');
  if (desktopView) {
    const isDesktopToday = desktopView.getAttribute('data-is-today') === 'true';
    const cards = desktopView.querySelectorAll('[data-start-time]');
    cards.forEach((card) => {
      const start = card.getAttribute('data-start-time');
      const end = card.getAttribute('data-end-time');
      const isNow = isDesktopToday && Boolean(start && end && start <= currentTimeStr && currentTimeStr <= end);
      toggleCardNow(card, isNow, false);
    });
  }
}

function initMobileWeekScrollSpy() {
  if (!mobileScrollSpyInitialized) {
    window.addEventListener('scroll', updateMobileActiveDayTab, { passive: true });
    mobileScrollSpyInitialized = true;
  }
  updateMobileActiveDayTab();
}

function initPageBehaviour() {
  syncDashboardLinks();
  initMobileDayPosition();
  initMobileWeekScrollSpy();
  updateCurrentLessonBadges();
}

document.addEventListener('DOMContentLoaded', () => {
  initModals();
  initPageBehaviour();
  setInterval(updateCurrentLessonBadges, 30000);
});

// Quick Add Homework Helper (fills subject, lesson, due date and opens modal)
function openAddHwModal(subjectId, lessonId, dueDate) {
  const modal = document.getElementById('add-hw-modal');
  if (!modal) return;
  if (subjectId) {
    const subjSelect = modal.querySelector('#subject_id');
    if (subjSelect) subjSelect.value = String(subjectId);
  }
  if (dueDate) {
    const dueInput = modal.querySelector('#due_date');
    if (dueInput) dueInput.value = dueDate;
  }
  syncDateDisplays(modal);
  const lessonInput = modal.querySelector('#hw_lesson_id');
  if (lessonInput) {
    lessonInput.value = lessonId ? String(lessonId) : '';
  }
  // An explicit quick-add context (for example, from a lesson card) wins over
  // the automatic "current lesson" suggestion.
  modal.dataset.skipNextLessonAuto = '1';
  openModal('add-hw-modal');
}

// Mobile week switch animation state & smooth transition handler
let isSwitchingWeek = false;

async function switchMobileWeek(targetUrl, direction = 'next', pushHistory = true) {
  if (isSwitchingWeek) return;

  const mobileView = document.getElementById('mobile-week-view');
  if (!mobileView) {
    window.location.href = targetUrl;
    return;
  }

  isSwitchingWeek = true;

  const outClass = direction === 'next' ? 'anim-week-slide-out-left' : 'anim-week-slide-out-right';
  const inClass = direction === 'next' ? 'anim-week-slide-in-right' : 'anim-week-slide-in-left';

  try {
    const fetchPromise = fetch(targetUrl, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });

    mobileView.classList.remove('anim-week-slide-in-left', 'anim-week-slide-in-right', 'anim-week-slide-out-left', 'anim-week-slide-out-right');
    void mobileView.offsetWidth; // Force reflow
    mobileView.classList.add(outClass);

    const [res] = await Promise.all([
      fetchPromise,
      new Promise((resolve) => setTimeout(resolve, 160))
    ]);

    if (!res.ok) {
      throw new Error(`HTTP error ${res.status}`);
    }

    const html = await res.text();
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');
    const newMobileView = doc.getElementById('mobile-week-view');

    if (!newMobileView) {
      window.location.href = targetUrl;
      return;
    }

    // Determine whether incoming week is current week and find target focus day
    const isCurWeek = newMobileView.getAttribute('data-is-current-week') === 'true';
    const todayDayNum = newMobileView.getAttribute('data-today-day-num');
    const targetDayNum = (isCurWeek && todayDayNum) ? todayDayNum : '1';

    // Ensure incoming tabs start with the target day active so no tab-switching flicker occurs
    const newTabs = newMobileView.querySelectorAll('.mobile-day-tab');
    newTabs.forEach((tab) => {
      const isTarget = String(tab.getAttribute('data-day-num')) === String(targetDayNum);
      const badge = tab.querySelector('.day-badge');
      const label = tab.querySelector('.day-label');
      if (badge && label) {
        if (isTarget) {
          badge.classList.remove('text-zinc-400', 'bg-transparent');
          badge.classList.add('bg-emerald-500', 'text-white', 'shadow-md', 'shadow-emerald-500/25');
          label.classList.remove('text-zinc-500');
          label.classList.add('text-emerald-400');
        } else {
          badge.classList.remove('bg-emerald-500', 'text-white', 'shadow-md', 'shadow-emerald-500/25');
          badge.classList.add('text-zinc-400', 'bg-transparent');
          label.classList.remove('text-emerald-400');
          label.classList.add('text-zinc-500');
        }
      }
    });

    // Swap mobile view DOM and container attributes
    mobileView.innerHTML = newMobileView.innerHTML;
    if (newMobileView.hasAttribute('data-is-current-week')) {
      mobileView.setAttribute('data-is-current-week', newMobileView.getAttribute('data-is-current-week'));
    }
    if (newMobileView.hasAttribute('data-today-day-num')) {
      mobileView.setAttribute('data-today-day-num', newMobileView.getAttribute('data-today-day-num'));
    }

    // Scroll positioning: smoothly scroll from top to today for current week, or top for other weeks
    if (isCurWeek && targetDayNum && targetDayNum !== '1') {
      isProgrammaticScroll = true;
      setActiveMobileDayTab(targetDayNum);
      window.scrollTo({ top: 0, behavior: 'instant' });

      const targetSection = document.getElementById('mobile-day-' + targetDayNum);
      if (targetSection) {
        setTimeout(() => {
          targetSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
          if (programmaticScrollTimeout) clearTimeout(programmaticScrollTimeout);
          programmaticScrollTimeout = setTimeout(() => {
            isProgrammaticScroll = false;
            updateMobileActiveDayTab();
          }, 850);
        }, 60);
      } else {
        isProgrammaticScroll = false;
      }
    } else {
      window.scrollTo({ top: 0, behavior: 'instant' });
    }

    updateCurrentLessonBadges();

    // Sync desktop view in DOM if present
    const newDesktopView = doc.getElementById('desktop-dashboard-view');
    const curDesktopView = document.getElementById('desktop-dashboard-view');
    if (newDesktopView && curDesktopView) {
      curDesktopView.innerHTML = newDesktopView.innerHTML;
      if (newDesktopView.hasAttribute('data-is-today')) {
        curDesktopView.setAttribute('data-is-today', newDesktopView.getAttribute('data-is-today'));
      }
    }

    // Sync modal values
    const newDue = doc.getElementById('due_date');
    const curDue = document.getElementById('due_date');
    if (newDue && curDue) curDue.value = newDue.value;

    const newReturnUrl = doc.querySelector('input[name="return_url"]');
    const curReturnUrl = document.querySelector('input[name="return_url"]');
    if (newReturnUrl && curReturnUrl) curReturnUrl.value = newReturnUrl.value;

    syncDateDisplays();

    if (pushHistory) {
      window.history.pushState({ locusDateUrl: targetUrl }, '', targetUrl);
    }
    if (doc.title) {
      document.title = doc.title;
    }

    // Keep the selected week in sync with sidebar/dock "Дневник" links
    syncDashboardLinks();

    // Re-initialize HTMX bindings on the newly swapped DOM
    if (window.htmx) {
      window.htmx.process(mobileView);
      if (curDesktopView) {
        window.htmx.process(curDesktopView);
      }
    }

    // Re-calculate active scroll-spy ribbon tab
    initMobileWeekScrollSpy();

    // Seamlessly transition animation classes without intermediate unstyled reflow
    mobileView.classList.remove(outClass);
    mobileView.classList.add(inClass);

    setTimeout(() => {
      mobileView.classList.remove(inClass);
      isSwitchingWeek = false;
    }, 220);

  } catch (err) {
    console.warn('Week switch fetch error, falling back to full navigation:', err);
    mobileView.classList.remove(outClass, inClass);
    isSwitchingWeek = false;
    window.location.href = targetUrl;
  }
}

// Intercept clicks on mobile week switcher arrows for animated transition
document.addEventListener('click', (e) => {
  const prevBtn = e.target.closest('[data-swipe-prev]');
  if (prevBtn) {
    e.preventDefault();
    if (prevBtn.href) {
      switchMobileWeek(prevBtn.href, 'prev');
    }
    return;
  }

  const nextBtn = e.target.closest('[data-swipe-next]');
  if (nextBtn) {
    e.preventDefault();
    if (nextBtn.href) {
      switchMobileWeek(nextBtn.href, 'next');
    }
    return;
  }
});

// Unified touch & pointer swipe navigation for mobile & devtools device toolbar
let pointerStartX = 0;
let pointerStartY = 0;
let pointerStartTime = 0;
let isPointerActive = false;

function handleGestureStart(x, y) {
  pointerStartX = x;
  pointerStartY = y;
  pointerStartTime = Date.now();
  isPointerActive = true;
}

function handleGestureEnd(x, y) {
  if (!isPointerActive) return;
  isPointerActive = false;

  const dx = x - pointerStartX;
  const dy = y - pointerStartY;
  const dt = Date.now() - pointerStartTime;

  // Horizontal gesture threshold: at least 70px, predominantly horizontal (1.8x dy), under 700ms
  if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.8 && dt < 700) {
    const activeEl = document.activeElement;
    if (activeEl && ['INPUT', 'TEXTAREA', 'SELECT'].includes(activeEl.tagName)) {
      return;
    }
    const openModalEl = document.querySelector('[data-modal]:not(.hidden)');
    if (openModalEl) return;

    if (dx < 0) {
      // Swiped left -> Next week
      const nextLink = document.querySelector('[data-swipe-next]');
      if (nextLink && nextLink.href) {
        switchMobileWeek(nextLink.href, 'next');
      }
    } else {
      // Swiped right -> Previous week
      const prevLink = document.querySelector('[data-swipe-prev]');
      if (prevLink && prevLink.href) {
        switchMobileWeek(prevLink.href, 'prev');
      }
    }
  }
}

// Touch events for real mobile devices
document.addEventListener('touchstart', (e) => {
  if (e.touches.length === 1) {
    handleGestureStart(e.touches[0].clientX, e.touches[0].clientY);
  }
}, { passive: true });

document.addEventListener('touchend', (e) => {
  if (e.changedTouches.length === 1) {
    handleGestureEnd(e.changedTouches[0].clientX, e.changedTouches[0].clientY);
  }
}, { passive: true });

// Mouse drag events for PC browser Device Toolbar / responsive mode
document.addEventListener('mousedown', (e) => {
  if (e.button === 0 && window.innerWidth < 768) {
    handleGestureStart(e.clientX, e.clientY);
  }
});

document.addEventListener('mouseup', (e) => {
  if (e.button === 0 && window.innerWidth < 768) {
    handleGestureEnd(e.clientX, e.clientY);
  }
});
