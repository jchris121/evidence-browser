/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./static/**/*.{html,js}", "./mockup/**/*.html"],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        'evidence': {
          950: '#0a0d12',
          900: '#0d1117',
          850: '#11151c',
          800: '#161b22',
          750: '#1b2028',
          700: '#21262d',
          600: '#30363d',
          500: '#484f58',
        }
      }
    }
  },
  plugins: [],
}
