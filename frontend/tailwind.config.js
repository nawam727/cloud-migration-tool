/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",  // <-- This is important!
    "./public/index.html"           // optional, for static HTML
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
