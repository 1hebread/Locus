/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/locus/templates/**/*.html',
    './src/locus/static/js/**/*.js',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#000000',
          panel: '#000000',
          card: '#000000',
          subtle: '#121214',
        },
        accent: {
          DEFAULT: '#2ea35b',
          hover: '#247c45',
          dark: '#1d6537',
        },
        emerald: {
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
    },
  },
};
