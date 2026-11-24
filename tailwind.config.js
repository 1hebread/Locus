/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/locus/templates/**/*.html',
    './src/locus/static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        // Themeable surfaces (values live in app.css)
        surface: {
          DEFAULT: 'rgb(var(--c-surface) / <alpha-value>)',
          card: 'rgb(var(--c-surface-card) / <alpha-value>)',
          raised: 'rgb(var(--c-surface-raised) / <alpha-value>)',
          subtle: 'rgb(var(--c-surface-subtle) / <alpha-value>)',
          inset: 'rgb(var(--c-surface-inset) / <alpha-value>)',
          strong: 'rgb(var(--c-surface-strong) / <alpha-value>)',
          active: 'rgb(var(--c-surface-active) / <alpha-value>)',
        },
        edge: {
          DEFAULT: 'rgb(var(--c-edge) / <alpha-value>)',
          strong: 'rgb(var(--c-edge-strong) / <alpha-value>)',
          extra: 'rgb(var(--c-edge-extra) / <alpha-value>)',
        },
        fg: {
          DEFAULT: 'rgb(var(--c-fg) / <alpha-value>)',
          soft: 'rgb(var(--c-fg-soft) / <alpha-value>)',
          muted: 'rgb(var(--c-fg-muted) / <alpha-value>)',
          subtle: 'rgb(var(--c-fg-subtle) / <alpha-value>)',
          faint: 'rgb(var(--c-fg-faint) / <alpha-value>)',
          ghost: 'rgb(var(--c-fg-ghost) / <alpha-value>)',
        },
        accent: {
          DEFAULT: 'rgb(var(--c-accent) / <alpha-value>)',
          hover: 'rgb(var(--c-accent-hover) / <alpha-value>)',
          active: 'rgb(var(--c-accent-active) / <alpha-value>)',
          line: 'rgb(var(--c-accent-line) / <alpha-value>)',
          ink: 'rgb(var(--c-accent-ink) / <alpha-value>)',
          'ink-hover': 'rgb(var(--c-accent-ink-hover) / <alpha-value>)',
          contrast: 'rgb(var(--c-accent-contrast) / <alpha-value>)',
        },
        'on-accent': 'rgb(var(--c-on-accent) / <alpha-value>)',
        danger: {
          DEFAULT: 'rgb(var(--c-danger) / <alpha-value>)',
          hover: 'rgb(var(--c-danger-hover) / <alpha-value>)',
          ink: 'rgb(var(--c-danger-ink) / <alpha-value>)',
          'ink-soft': 'rgb(var(--c-danger-ink-soft) / <alpha-value>)',
          soft: 'rgb(var(--c-danger-soft) / <alpha-value>)',
          edge: 'rgb(var(--c-danger-edge) / <alpha-value>)',
        },
        warning: {
          ink: 'rgb(var(--c-warning-ink) / <alpha-value>)',
        },
        info: {
          ink: 'rgb(var(--c-info-ink) / <alpha-value>)',
        },
        // Fixed brand green (week ribbon, gradient headers, badges)
        brand: {
          50: '#f0fdf4',
          100: '#dcfce7',
          200: '#bbf7d0',
          300: '#86efac',
          400: '#34b566',
          500: '#2ea35b',
          600: '#247c45',
          700: '#1d6537',
          800: '#17522c',
          900: '#134324',
          950: '#0a2614',
        },
      },
      boxShadow: {
        card: 'var(--shadow-card)',
        glow: 'var(--shadow-glow)',
        'glow-strong': 'var(--shadow-glow-strong)',
      },
      backgroundImage: {
        'brand-gradient': 'linear-gradient(to bottom, #28c76f 0%, #22b561 55%, #1ca254 100%)',
      },
    },
  },
};
