import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class", ".dark-theme"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Geist", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Geist", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["Geist Mono", "Geist", "ui-monospace", "SFMono-Regular", "monospace"]
      },
      colors: {
        ink: "#071018",
        glass: "rgba(255, 255, 255, 0.08)",
        cyan: "#fa4e03", // compatibility alias
        mint: "#fa4e03", // compatibility alias
        violet: "#141414", // compatibility alias
        accent: "#fa4e03", // Brand orange accent
        charcoal: "#141414", // Brand deep charcoal
        beige: "#fffbef" // Brand warm light background
      },
      boxShadow: {
        glass: "0 24px 80px rgba(6, 18, 34, 0.28)",
        glow: "0 0 80px rgba(85, 215, 255, 0.18)"
      },
      keyframes: {
        drift: {
          "0%, 100%": { transform: "translate3d(0, 0, 0)" },
          "50%": { transform: "translate3d(16px, -18px, 0)" }
        },
        scan: {
          "0%": { transform: "translateX(-110%)" },
          "100%": { transform: "translateX(110%)" }
        }
      },
      animation: {
        drift: "drift 9s ease-in-out infinite",
        scan: "scan 2.8s ease-in-out infinite"
      }
    }
  },
  plugins: []
};

export default config;
