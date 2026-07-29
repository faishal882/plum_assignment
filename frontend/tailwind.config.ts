import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "#e0e5ec",
        ink: "#3d4852",
        copy: "#606b75",
        violet: {
          DEFAULT: "#6c63ff",
          accent: "#8b84ff",
          pale: "#eeedff",
        },
        teal: {
          DEFAULT: "#38b2ac",
        },
        danger: "#dc4c64",
        hairline: "rgba(163, 177, 198, 0.42)",
        darkContrast: "#303842",
      },
      fontFamily: {
        display: ["Plus Jakarta Sans", "system-ui", "-apple-system", "sans-serif"],
        body: ["DM Sans", "system-ui", "-apple-system", "sans-serif"],
      },
      boxShadow: {
        "neu-raised": "9px 9px 16px rgba(163,177,198,.68), -9px -9px 16px rgba(255,255,255,.58)",
        "neu-raised-sm": "5px 5px 10px rgba(163,177,198,.62), -5px -5px 10px rgba(255,255,255,.56)",
        "neu-inset": "inset 6px 6px 10px rgba(163,177,198,.62), inset -6px -6px 10px rgba(255,255,255,.56)",
        "neu-inset-sm": "inset 3px 3px 6px rgba(163,177,198,.58), inset -3px -3px 6px rgba(255,255,255,.52)",
      },
      borderRadius: {
        label: "4px",
        control: "8px",
        card: "12px",
        frame: "16px",
      },
    },
  },
  plugins: [],
};

export default config;
