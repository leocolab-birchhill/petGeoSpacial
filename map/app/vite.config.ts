import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// PMTiles are fetched with HTTP Range requests; Vite dev server supports this
// out of the box. For production, any static server with Range support works.
// GitHub Pages project sites live under /petGeoSpacial/.
export default defineConfig({
  base: process.env.GITHUB_ACTIONS === "true" ? "/petGeoSpacial/" : "/",
  plugins: [react()],
  build: { sourcemap: true },
});
