// Register PWA Service Worker
if ('serviceWorker' in navigator) {
  const hadServiceWorker = Boolean(navigator.serviceWorker.controller);
  let isReloadingForSwUpdate = false;

  // Unregister legacy scoped registrations (/static/) to avoid scope conflicts
  navigator.serviceWorker.getRegistrations().then((registrations) => {
    for (const reg of registrations) {
      if (reg.scope && reg.scope.endsWith('/static/')) {
        reg.unregister().catch(() => {});
      }
    }
  }).catch(() => {});

  // Pick up a new SW immediately and reload once it takes control
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!hadServiceWorker || isReloadingForSwUpdate) return;
    isReloadingForSwUpdate = true;
    window.location.reload();
  });

  navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' })
    .then((reg) => {
      reg.update();
      console.log('Locus SW registered with scope:', reg.scope);
    })
    .catch((err) => {
      console.warn('Locus SW registration at /sw.js failed, trying /static/sw.js:', err);
      navigator.serviceWorker.register('/static/sw.js', { scope: '/', updateViaCache: 'none' })
        .then((reg) => reg.update())
        .catch((e) => console.error('Locus SW registration failed:', e));
    });
}

async function getReadyServiceWorkerRegistration(timeoutMs = 6000) {
  if (!('serviceWorker' in navigator)) return null;

  try {
    const reg = await navigator.serviceWorker.getRegistration('/');
    if (reg && reg.pushManager && reg.active) {
      return reg;
    }
  } catch (_) {}

  return await Promise.race([
    navigator.serviceWorker.ready,
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error('Таймаут инициализации Service Worker')), timeoutMs)
    ),
  ]);
}

// Web Push opt-in (homework change notifications)
function urlBase64ToUint8Array(base64String) {
  if (!base64String || typeof base64String !== 'string') {
    return new Uint8Array(0);
  }
  const clean = base64String.trim().replace(/^["']|["']$/g, '').trim();
  const padding = '='.repeat((4 - (clean.length % 4)) % 4);
  const base64 = (clean + padding).replace(/-/g, '+').replace(/_/g, '/');
  try {
    const raw = window.atob(base64);
    const outputArray = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; ++i) {
      outputArray[i] = raw.charCodeAt(i);
    }
    return outputArray;
  } catch (e) {
    console.error('Failed to decode base64 VAPID key:', e);
    return new Uint8Array(0);
  }
}

function isPushSupported() {
  if (!('serviceWorker' in navigator) || !('Notification' in window)) return false;
  return 'PushManager' in window || 'pushManager' in ServiceWorkerRegistration.prototype;
}

function isIosDevice() {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

function isStandalonePwa() {
  return window.navigator.standalone === true || window.matchMedia('(display-mode: standalone)').matches;
}

function extractPushSubscriptionData(subscription) {
  if (!subscription) return null;
  const json = subscription.toJSON ? subscription.toJSON() : {};
  const keys = json.keys || {};
  let p256dh = (typeof keys.p256dh === 'string' && keys.p256dh) ? keys.p256dh : '';
  let auth = (typeof keys.auth === 'string' && keys.auth) ? keys.auth : '';

  if (!p256dh && subscription.getKey) {
    try {
      const rawKey = subscription.getKey('p256dh');
      if (rawKey) {
        p256dh = btoa(String.fromCharCode.apply(null, new Uint8Array(rawKey)))
          .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
      }
    } catch (_) {}
  }
  if (!auth && subscription.getKey) {
    try {
      const rawAuth = subscription.getKey('auth');
      if (rawAuth) {
        auth = btoa(String.fromCharCode.apply(null, new Uint8Array(rawAuth)))
          .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
      }
    } catch (_) {}
  }
  return {
    endpoint: subscription.endpoint,
    keys: { p256dh, auth }
  };
}

function setPushState(enabled) {
  document.querySelectorAll('[data-push-toggle]').forEach((button) => {
    button.classList.toggle('text-emerald-400', enabled);
    button.classList.toggle('text-zinc-400', !enabled);
    button.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    const title = enabled ? 'Уведомления включены' : 'Включить уведомления';
    button.title = title;
    button.setAttribute('aria-label', title);
  });
  document.querySelectorAll('[data-push-label]').forEach((label) => {
    label.textContent = enabled ? 'Уведомления вкл.' : 'Уведомления';
  });
}

let isTogglingPush = false;

async function togglePushNotifications() {
  if (isTogglingPush) return;
  isTogglingPush = true;

  const hideButtons = () => {
    document.querySelectorAll('[data-push-toggle]').forEach((btn) => btn.classList.add('hidden'));
  };

  try {
    // iOS outside PWA prompt
    if (isIosDevice() && !isStandalonePwa()) {
      alert('В iOS уведомления работают только в установленном приложении: нажмите «Поделиться» → «На экран Домой», затем запустите Locus с иконки.');
      return;
    }

    // Ask first: keep synchronous to prevent iOS from dropping user activation gesture
    if (Notification.permission !== 'granted') {
      if (Notification.permission === 'denied') {
        alert('Уведомления заблокированы в настройках браузера. Разрешите их для Locus и попробуйте снова.');
        hideButtons();
        return;
      }
      const perm = await Notification.requestPermission();
      if (perm === 'denied') {
        hideButtons();
        return;
      }
      if (perm !== 'granted') return;
    }

    const config = await loadPushConfig();
    if (!config || !config.enabled) {
      alert('Уведомления не настроены на сервере (отсутствуют VAPID ключи).');
      return;
    }

    const registration = await getReadyServiceWorkerRegistration(8000);

    if (!registration || !registration.pushManager) {
      throw new Error('PushManager недоступен в текущем браузере.');
    }

    const serverKey = urlBase64ToUint8Array(config.public_key);
    if (!serverKey || serverKey.byteLength !== 65 || serverKey[0] !== 4) {
      const len = serverKey ? serverKey.byteLength : 0;
      console.error('Invalid VAPID public key:', config.public_key, 'Decoded length:', len);
      throw new Error(
        `Некорректный VAPID_PUBLIC_KEY на сервере (длина ${len} байт вместо 65). ` +
        `Убедитесь, что в переменных окружения на проде задан именно публичный ключ из 'uv run locus-vapid' (начинается на B..., 87 символов), а не приватный ключ.`
      );
    }

    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      try {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: serverKey,
        });
      } catch (subErr) {
        // If an old conflicting subscription exists, reset it and retry
        const staleSub = await registration.pushManager.getSubscription();
        if (staleSub) {
          await staleSub.unsubscribe().catch(() => {});
          subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: serverKey,
          });
        } else {
          throw subErr;
        }
      }
    }

    if (subscription) {
      const payload = extractPushSubscriptionData(subscription);
      if (!payload || !payload.keys || !payload.keys.p256dh || !payload.keys.auth) {
        throw new Error('Не удалось извлечь ключи шифрования push-подписки из браузера.');
      }

      const response = await fetch('/push/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (response.ok) {
        pushSubscribed = true;
        pushSyncedThisSession = true;
        hideButtons();
      } else {
        const errorDetail = await response.text();
        console.error('Ошибка сохранения push-подписки:', response.status, errorDetail);
        alert('Не удалось сохранить push-подписку на сервере (код ' + response.status + '). Проверьте логи сервера.');
      }
    }
  } catch (error) {
    console.error('Push subscription failed:', error);
    alert('Не удалось включить уведомления: ' + (error.message || error));
  } finally {
    isTogglingPush = false;
  }
}

let pushConfigPromise = null;
let pushSubscribed = false;
let pushSyncedThisSession = false;
let isRefreshingPushUI = false;

function loadPushConfig() {
  if (!pushConfigPromise) {
    pushConfigPromise = fetch('/push/config')
      .then((response) => (response.ok ? response.json() : null))
      .catch(() => null)
      .then((data) => {
        if (!data) pushConfigPromise = null;
        return data;
      });
  }
  return pushConfigPromise;
}

// Preload push configuration as early as possible so user gestures are not lost in iOS WebKit
if ('serviceWorker' in navigator) {
  loadPushConfig();
}

// Runs on load and after client-side navigation, when the dock/sidebar markup is re-rendered
async function refreshPushUI() {
  if (isRefreshingPushUI) return;
  isRefreshingPushUI = true;

  try {
    const buttons = document.querySelectorAll('[data-push-toggle]');
    if (!buttons.length) return;

    const hide = () => buttons.forEach((button) => button.classList.add('hidden'));
    const show = () => buttons.forEach((button) => button.classList.remove('hidden'));

    if (!('serviceWorker' in navigator)) return hide();

    const config = await loadPushConfig();
    const hasNotification = 'Notification' in window;
    const supported = isPushSupported() || (isIosDevice() && !isStandalonePwa());
    if (!config || !config.enabled || !supported) return hide();

    // 1. Explicitly blocked in browser settings: hide per user request
    if (hasNotification && Notification.permission === 'denied') {
      return hide();
    }

    // 2. Default ("Спрашивать"): user has not granted or denied notifications yet.
    if (hasNotification && Notification.permission === 'default') {
      show();
      return setPushState(false);
    }

    // 3. Granted ("Разрешено"):
    if (hasNotification && Notification.permission === 'granted') {
      if (!isIosDevice()) {
        // Desktop / Android: notifications are permitted, hide the bell immediately
        hide();
        if (!pushSyncedThisSession) {
          try {
            const registration = await getReadyServiceWorkerRegistration(4000);
            if (registration && registration.pushManager) {
              let subscription = await registration.pushManager.getSubscription();
              const serverKey = urlBase64ToUint8Array(config.public_key);
              if (serverKey && serverKey.byteLength === 65 && serverKey[0] === 4) {
                if (!subscription) {
                  subscription = await registration.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: serverKey,
                  }).catch(() => null);
                }
              }
              if (subscription) {
                const payload = extractPushSubscriptionData(subscription);
                if (payload && payload.keys && payload.keys.p256dh && payload.keys.auth) {
                  const response = await fetch('/push/subscribe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                  });
                  if (response.ok) {
                    pushSubscribed = true;
                    pushSyncedThisSession = true;
                  } else {
                    console.warn('Фоновая синхронизация push не удалась:', response.status);
                  }
                }
              }
            }
          } catch (error) {
            console.warn('Background push sync failed:', error);
          }
        }
        return;
      }

      // iOS WebKit: subscribe() requires a user click.
      try {
        const registration = await getReadyServiceWorkerRegistration(4000);
        if (registration && registration.pushManager) {
          const subscription = await registration.pushManager.getSubscription();
          if (subscription) {
            pushSubscribed = true;
            hide();
            if (!pushSyncedThisSession) {
              const payload = extractPushSubscriptionData(subscription);
              if (payload && payload.keys && payload.keys.p256dh && payload.keys.auth) {
                const response = await fetch('/push/subscribe', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(payload),
                });
                if (response.ok) {
                  pushSyncedThisSession = true;
                }
              }
            }
            return;
          }
        }
      } catch (error) {
        // Timeout or error on iOS
      }
      show();
      return setPushState(false);
    }

    // Fallback for iOS outside PWA
    show();
    setPushState(false);
  } finally {
    isRefreshingPushUI = false;
  }
}

// Delegated: survives sidebar/dock re-rendering during client-side navigation
document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-push-toggle]');
  if (!button) return;
  togglePushNotifications().catch((err) => {
    console.error('togglePushNotifications failed:', err);
  });
});

// Drop this browser's push subscription before logging out (shared devices).
// Delegated: the sidebar/menu forms are re-rendered during client-side navigation.
document.addEventListener('submit', (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.getAttribute('action') !== '/auth/logout') return;
  if (form.dataset.pushCleaned === '1' || !('serviceWorker' in navigator)) return;
  event.preventDefault();

  const finish = () => {
    form.dataset.pushCleaned = '1';
    form.submit();
  };
  const cleanup = getReadyServiceWorkerRegistration(2500)
    .then((registration) => registration && registration.pushManager ? registration.pushManager.getSubscription() : null)
    .then(async (subscription) => {
      if (!subscription) return;
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'push_endpoint';
      input.value = subscription.endpoint;
      form.appendChild(input);
      await subscription.unsubscribe();
    });

  // Never let a broken service worker block logout
  Promise.race([cleanup, new Promise((resolve) => setTimeout(resolve, 3000))])
    .catch(() => {})
    .finally(finish);
});

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', refreshPushUI);
} else {
  refreshPushUI();
}
window.addEventListener('load', refreshPushUI);

// Modal helpers with smooth fade transitions
const modalCloseTimeouts = new Map();
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
    if (Boolean(window.getSelection?.()?.toString())) return;
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
  const pendingClose = modalCloseTimeouts.get(id);
  if (pendingClose) {
    clearTimeout(pendingClose);
    modalCloseTimeouts.delete(id);
  }
  const modal = document.getElementById(id);
  if (modal) {
    delete modal.dataset.closing;
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
    void modal.offsetWidth; // Firefox needs a committed start frame for the open transition
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
    // Marks the modal while its fade-out runs, so a page swap neither
    // re-shows it nor replaces the animating sheet mid-flight
    modal.dataset.closing = '1';
    if (modalCloseTimeouts.has(id)) {
      clearTimeout(modalCloseTimeouts.get(id));
    }
    modalCloseTimeouts.set(id, setTimeout(() => {
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
          // The page switch scrolls to the top itself; restoring the old
          // position here would fight it
          if (!isNavigatingPage) {
            window.scrollTo({ top: modalScrollY, behavior: 'instant' });
          }
        }
        if (id === 'lesson-detail-modal') {
          const container = document.getElementById('lesson-modal-container');
          if (container) container.innerHTML = '';
        }
      }
      delete modal.dataset.closing;
      modalCloseTimeouts.delete(id);
    }, 260));
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
    if (modal.dataset.closing) return; // fading out after a page switch
    void modal.offsetWidth; // Firefox needs a committed start frame for the open transition
    requestAnimationFrame(() => {
      if (!modal.classList.contains('hidden')) {
        modal.classList.add('modal-visible');
      }
    });
    document.body.style.overflow = 'hidden';
  });
}

// Track pointer/mouse down location to distinguish deliberate backdrop clicks
// from text selection drags that started inside the modal and ended outside on the backdrop.
let isPointerDownInsideModal = false;

function handlePointerDownModalCheck(e) {
  const openModal = e.target.closest('[data-modal].modal-visible') || document.querySelector('[data-modal].modal-visible');
  if (!openModal) {
    isPointerDownInsideModal = false;
    return;
  }
  const sheet = openModal.lastElementChild;
  isPointerDownInsideModal = !!(sheet && sheet.contains(e.target));
}

document.addEventListener('pointerdown', handlePointerDownModalCheck, true);
document.addEventListener('mousedown', handlePointerDownModalCheck, true);

function handlePointerUpModalCheck() {
  if (!isPointerDownInsideModal) return;
  setTimeout(() => {
    isPointerDownInsideModal = false;
  }, 100);
}

document.addEventListener('pointerup', handlePointerUpModalCheck, true);
document.addEventListener('mouseup', handlePointerUpModalCheck, true);
document.addEventListener('pointercancel', () => { isPointerDownInsideModal = false; }, true);

// Close modal when clicking on backdrop container or backdrop overlay,
// but NEVER close if the interaction started as a text selection / drag inside the modal.
window.addEventListener('click', (e) => {
  const openModal = e.target.closest('[data-modal].modal-visible');
  if (!openModal) return;

  const sheet = openModal.lastElementChild;
  const isClickInside = !!(sheet && sheet.contains(e.target));

  if (!isClickInside) {
    if (isPointerDownInsideModal) {
      isPointerDownInsideModal = false;
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      return;
    }

    closeModal(openModal.id);
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();
  }
}, true);

// ============================================================
// Client-side section navigation (Dock + Sidebar)
// Pages fade into each other instead of doing a full reload.
// ============================================================
let isNavigatingPage = false;
let lastPagePath = window.location.pathname;
let lastPageUrl = window.location.pathname + window.location.search;
const SECTION_PATHS = new Set(['/', '/homework', '/subjects', '/schedule', '/admin/users', '/admin/history', '/admin/api-keys']);

// Inline <script> tags inserted via innerHTML never run, so re-create them
function runScripts(container) {
  container.querySelectorAll('script').forEach((oldScript) => {
    const script = document.createElement('script');
    Array.from(oldScript.attributes).forEach((attr) => script.setAttribute(attr.name, attr.value));
    script.textContent = oldScript.textContent;
    oldScript.replaceWith(script);
  });
}

// Dismiss any open modal/menu while swapping the page: it fades out over the
// incoming page instead of disappearing abruptly
function hideOpenOverlays() {
  if (document.activeElement && document.activeElement.blur) {
    document.activeElement.blur();
  }
  document.querySelectorAll('[data-modal]:not(.hidden)').forEach((modal) => {
    if (modal.id) closeModal(modal.id);
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

// The add-homework modal is rendered outside the dashboard content that gets
// swapped on navigation, so its "next lesson" quick-fill must be refreshed
// from the newly fetched page by hand.
function syncNextLessonSuggestion(doc) {
  const current = document.querySelector('#add-hw-modal [data-next-lesson-btn]');
  const fresh = doc.querySelector('#add-hw-modal [data-next-lesson-btn]');
  if (current && fresh) {
    current.replaceWith(fresh);
  } else if (current) {
    current.remove();
  } else if (fresh) {
    const form = document.querySelector('#add-hw-modal form');
    if (form) form.prepend(fresh);
  }
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
    const isGender = selectedOpt && selectedOpt.getAttribute('data-is-gender') === 'true';
    const userSubgroup = subgroupSelect.getAttribute('data-user-subgroup');
    const userGender = subgroupSelect.getAttribute('data-user-gender');
    if (isGender) {
      if (userGender && subgroupSelect.querySelector('option[value="' + userGender + '"]')) {
        subgroupSelect.value = userGender;
      } else {
        subgroupSelect.value = '';
      }
    } else {
      if (userSubgroup && subgroupSelect.querySelector('option[value="' + userSubgroup + '"]')) {
        subgroupSelect.value = userSubgroup;
      } else {
        subgroupSelect.value = '';
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

  const desktopView = document.getElementById('desktop-dashboard-view');
  const isDesktop = window.innerWidth >= 768;
  const isDesktopToday = desktopView ? desktopView.getAttribute('data-is-today') === 'true' : true;

  const button = modal.querySelector('[data-next-lesson-btn]');
  if (
    button &&
    !button.classList.contains('hidden') &&
    (!isDesktop || isDesktopToday) &&
    button.getAttribute('data-auto-apply') === 'true'
  ) {
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

// Split "Save" button in the lesson modal: the arrow opens the extra
// destinations (next lesson / both groups).
function hideSplitPanel(panel, toggle) {
  if (toggle) toggle.setAttribute('aria-expanded', 'false');
  if (panel.classList.contains('hidden') || panel.classList.contains('split-menu-closing')) return;
  panel.classList.add('split-menu-closing');
  panel.addEventListener('animationend', (e) => {
    if (e.target !== panel) return;
    panel.classList.remove('split-menu-closing');
    panel.classList.add('hidden');
  }, { once: true });
}

function closeSplitMenus(except) {
  document.querySelectorAll('[data-split-menu-panel]:not(.hidden)').forEach((panel) => {
    if (panel === except) return;
    const toggle = panel.closest('[data-split-menu]')?.querySelector('[data-split-toggle]');
    hideSplitPanel(panel, toggle);
  });
}

document.addEventListener('click', (e) => {
  const toggle = e.target.closest ? e.target.closest('[data-split-toggle]') : null;
  if (toggle) {
    const menu = toggle.closest('[data-split-menu]');
    const panel = menu ? menu.querySelector('[data-split-menu-panel]') : null;
    if (!panel) return;
    // A tap during the close animation simply reopens the menu.
    if (panel.classList.contains('split-menu-closing')) {
      panel.classList.remove('split-menu-closing');
      panel.classList.remove('hidden');
      toggle.setAttribute('aria-expanded', 'true');
      return;
    }
    closeSplitMenus(panel);
    if (panel.classList.contains('hidden')) {
      panel.classList.remove('hidden');
      toggle.setAttribute('aria-expanded', 'true');
    } else {
      hideSplitPanel(panel, toggle);
    }
    return;
  }

  if (e.target.closest && e.target.closest('[data-split-menu-panel]')) return;
  if (e.target.closest && e.target.closest('[data-split-menu]')) return;
  closeSplitMenus();
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
  // Skip while the menu is fading out: replacing its markup would cut the animation
  if (newMobileMenu && curMobileMenu && !curMobileMenu.dataset.closing) {
    curMobileMenu.innerHTML = newMobileMenu.innerHTML;
  }

  refreshPushUI();
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
  const targetDate = targetURL.searchParams.get('date');

  // Check if target day pane exists within the currently rendered week and subgroup
  const currentView = document.getElementById('desktop-dashboard-view');
  const defaultDate = currentView ? currentView.getAttribute('data-default-date') : null;
  const effectiveDate = targetDate || defaultDate;
  const currentSubgroup = currentView ? (currentView.getAttribute('data-current-subgroup') || 'all') : 'all';
  const targetSubgroup = targetURL.searchParams.get('subgroup') || 'all';

  const isSameSubgroup = (targetSubgroup === currentSubgroup);
  const targetPane = (isSameSubgroup && effectiveDate) ? document.getElementById('desktop-day-pane-' + effectiveDate) : null;

  if (targetPane) {
    const currentPane = content.querySelector('.desktop-day-pane:not(.hidden)');
    if (currentPane === targetPane) {
      return true;
    }

    isSwitchingDashboardDate = true;

    if (currentPane) {
      currentPane.classList.add('hidden');
    }
    targetPane.classList.remove('hidden');

    targetPane.classList.remove('anim-page-fade-in', 'anim-page-fade-out');
    void targetPane.offsetWidth; // Force reflow
    targetPane.classList.add('anim-page-fade-in');

    setTimeout(() => {
      targetPane.classList.remove('anim-page-fade-in');
      isSwitchingDashboardDate = false;
    }, 200);

    // Update active tab in the desktop week selector
    const tabs = selector.querySelectorAll('a[data-day-tab]');
    tabs.forEach((tab) => {
      if (tab.getAttribute('data-day-tab') === effectiveDate) {
        tab.classList.remove('bg-transparent', 'hover:bg-[#2b8f50]', 'text-white/90', 'font-extrabold');
        tab.classList.add('bg-[#2ea35b]', 'text-white', 'font-black', 'shadow-inner');
      } else {
        tab.classList.remove('bg-[#2ea35b]', 'shadow-inner', 'font-black');
        tab.classList.add('bg-transparent', 'hover:bg-[#2b8f50]', 'text-white/90', 'hover:text-white', 'font-extrabold');
      }
    });

    const isToday = targetPane.getAttribute('data-is-today') === 'true';
    if (currentView) {
      currentView.setAttribute('data-is-today', isToday ? 'true' : 'false');
    }

    const currentDue = document.getElementById('due_date');
    if (currentDue && effectiveDate) {
      currentDue.value = effectiveDate;
      syncDateDisplays();
    }

    const curModalSubtitle = document.getElementById('add-hw-modal-date-title');
    const targetDateText = targetPane.getAttribute('data-date-text');
    if (curModalSubtitle && targetDateText) {
      curModalSubtitle.textContent = targetDateText;
    }

    const currentReturnUrl = document.querySelector('#add-hw-modal input[name="return_url"]');
    if (currentReturnUrl) {
      currentReturnUrl.value = targetURL.pathname + targetURL.search;
    }

    const nextLessonBtn = document.querySelector('#add-hw-modal [data-next-lesson-btn]');
    if (nextLessonBtn) {
      nextLessonBtn.classList.toggle('hidden', !isToday);
    }

    const targetDayNum = targetPane.getAttribute('data-day-num');
    if (targetDayNum && typeof setActiveMobileDayTab === 'function') {
      setActiveMobileDayTab(targetDayNum);
    }

    lastPagePath = targetURL.pathname;
    lastPageUrl = targetUrlKey;

    if (push) {
      window.history.pushState({ locusDateUrl: targetUrl }, '', targetUrl);
    }

    syncDashboardLinks();
    updateCurrentLessonBadges();

    return true;
  }

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

    if (currentView) {
      ['data-is-today', 'data-default-date', 'data-current-subgroup'].forEach((attr) => {
        if (newView.hasAttribute(attr)) {
          currentView.setAttribute(attr, newView.getAttribute(attr));
        }
      });
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
    const curDue = document.getElementById('due_date');
    if (newDue && curDue) curDue.value = newDue.value;
    syncNextLessonSuggestion(doc);

    const newModalSubtitle = doc.getElementById('add-hw-modal-date-title');
    const curModalSubtitle = document.getElementById('add-hw-modal-date-title');
    if (newModalSubtitle && curModalSubtitle) {
      curModalSubtitle.textContent = newModalSubtitle.textContent;
    }

    const newReturnUrl = doc.querySelector('#add-hw-modal input[name="return_url"]');
    const curReturnUrl = document.querySelector('#add-hw-modal input[name="return_url"]');
    if (newReturnUrl && curReturnUrl) {
      curReturnUrl.value = newReturnUrl.value;
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
      ['data-is-today', 'data-default-date', 'data-current-subgroup'].forEach((attr) => {
        if (newDesktopView.hasAttribute(attr)) {
          curDesktopView.setAttribute(attr, newDesktopView.getAttribute(attr));
        }
      });
    }

    mobileView.innerHTML = newMobileView.innerHTML;
    syncNextLessonSuggestion(doc);
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

// Dashboard subgroup switch: refresh only the lesson lists, keeping the day
// header, week selector and subgroup buttons in place.
let isSwitchingDashboardSubgroup = false;

async function navigateDashboardSubgroup(targetUrl, push = true) {
  if (isSwitchingDashboardSubgroup) return false;

  const mobileView = document.getElementById('mobile-week-view');
  const desktopContent = document.getElementById('desktop-dashboard-content');
  const desktopSelector = document.getElementById('desktop-week-selector');
  if (!mobileView || (!desktopContent && !document.getElementById('desktop-day-lessons'))) {
    window.location.href = targetUrl;
    return false;
  }

  const targetURL = new URL(targetUrl, window.location.href);
  isSwitchingDashboardSubgroup = true;

  try {
    const res = await fetch(targetUrl, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);

    const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
    const newDesktopContent = doc.getElementById('desktop-dashboard-content');
    const newDesktopSelector = doc.getElementById('desktop-week-selector');

    if (desktopContent && newDesktopContent) {
      desktopContent.innerHTML = newDesktopContent.innerHTML;
      if (desktopSelector && newDesktopSelector) {
        desktopSelector.innerHTML = newDesktopSelector.innerHTML;
      }
      const curView = document.getElementById('desktop-dashboard-view');
      const targetSub = targetURL.searchParams.get('subgroup') || 'all';
      if (curView) {
        curView.setAttribute('data-current-subgroup', targetSub);
      }
    } else {
      const desktopLessons = document.getElementById('desktop-day-lessons');
      const newDesktopLessons = doc.getElementById('desktop-day-lessons');
      if (desktopLessons && newDesktopLessons) {
        desktopLessons.innerHTML = newDesktopLessons.innerHTML;
      }
      const curFilter = document.getElementById('desktop-subgroup-filter');
      const nextFilter = doc.getElementById('desktop-subgroup-filter');
      if (curFilter && nextFilter) curFilter.innerHTML = nextFilter.innerHTML;
    }

    // The add-homework modal lives outside the swapped area: refresh its
    // "next lesson" quick-fill so it follows the selected subgroup.
    syncNextLessonSuggestion(doc);

    // Keep modal return_url pointed at the current URL with subgroup
    const curReturnUrl = document.querySelector('#add-hw-modal input[name="return_url"]');
    if (curReturnUrl) {
      curReturnUrl.value = targetURL.pathname + targetURL.search;
    }

    // Only the active subgroup highlight changes above the lessons
    const curMobileFilter = document.getElementById('mobile-subgroup-filter');
    const nextMobileFilter = doc.getElementById('mobile-subgroup-filter');
    if (curMobileFilter && nextMobileFilter) {
      curMobileFilter.innerHTML = nextMobileFilter.innerHTML;
    }

    mobileView.querySelectorAll('.mobile-day-lessons').forEach((cur) => {
      const dayNum = cur.getAttribute('data-day-num');
      const next = doc.querySelector(`.mobile-day-lessons[data-day-num="${dayNum}"]`);
      if (next) cur.innerHTML = next.innerHTML;
    });

    updateCurrentLessonBadges();

    lastPagePath = targetURL.pathname;
    lastPageUrl = targetURL.pathname + targetURL.search;

    if (push) {
      window.history.pushState({ locusDateUrl: targetUrl }, '', targetUrl);
    }

    if (window.htmx) {
      if (desktopContent) window.htmx.process(desktopContent);
      window.htmx.process(mobileView);
    }

    return true;
  } catch (err) {
    console.warn('Subgroup switch failed, falling back to full navigation:', err);
    window.location.href = targetUrl;
    return false;
  } finally {
    isSwitchingDashboardSubgroup = false;
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
    navigateDashboardSubgroup(url.pathname + url.search);
  } else {
    navigateToPage(url.pathname + url.search);
  }
});

// Browser Back/Forward: page switch, or week switch while on the dashboard
function isSubgroupOnlyChange(fromUrl, toUrl) {
  if (!fromUrl || !toUrl) return false;
  const param = (url, key) => new URL(url, window.location.origin).searchParams.get(key);
  const currentView = document.getElementById('desktop-dashboard-view');
  const defaultDate = currentView ? currentView.getAttribute('data-default-date') : null;
  const fromDate = param(fromUrl, 'date') || defaultDate;
  const toDate = param(toUrl, 'date') || defaultDate;
  const fromSub = param(fromUrl, 'subgroup') || 'all';
  const toSub = param(toUrl, 'subgroup') || 'all';
  return fromDate === toDate && fromSub !== toSub;
}

window.addEventListener('popstate', () => {
  const targetPath = window.location.pathname;
  const targetUrl = targetPath + window.location.search;

  if (targetPath === '/' && lastPagePath === '/' && isSubgroupOnlyChange(lastPageUrl, targetUrl)) {
    navigateDashboardSubgroup(targetUrl, false);
    return;
  }

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
  const desktopPanes = document.querySelectorAll('.desktop-day-pane');
  if (desktopPanes.length > 0) {
    desktopPanes.forEach((pane) => {
      const isDayToday = pane.getAttribute('data-is-today') === 'true';
      const cards = pane.querySelectorAll('[data-start-time]');
      cards.forEach((card) => {
        const start = card.getAttribute('data-start-time');
        const end = card.getAttribute('data-end-time');
        const isNow = isDayToday && Boolean(start && end && start <= currentTimeStr && currentTimeStr <= end);
        toggleCardNow(card, isNow, false);
      });
    });
  } else {
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
    syncNextLessonSuggestion(doc);
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
      ['data-is-today', 'data-default-date', 'data-current-subgroup'].forEach((attr) => {
        if (newDesktopView.hasAttribute(attr)) {
          curDesktopView.setAttribute(attr, newDesktopView.getAttribute(attr));
        }
      });
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
