/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        msrit: {
          navy:  '#1a3560',
          blue:  '#2458a8',
          gold:  '#e07b2a',
        },
      },
      keyframes: {
        bounce3: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%':      { transform: 'translateY(-6px)' },
        },
      },
      animation: {
        'd0': 'bounce3 1s ease-in-out infinite',
        'd1': 'bounce3 1s ease-in-out 0.2s infinite',
        'd2': 'bounce3 1s ease-in-out 0.4s infinite',
      },
    },
  },
  plugins: [],
}
