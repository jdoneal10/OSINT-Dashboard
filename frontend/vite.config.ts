/// <reference types="vitest/config" />
import { createReadStream, statSync } from 'node:fs'
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

const BASEMAP_DIR = path.resolve(import.meta.dirname, '../data/basemap')
const MIME: Record<string, string> = {
  '.pmtiles': 'application/octet-stream',
  '.pbf': 'application/x-protobuf',
  '.json': 'application/json',
  '.png': 'image/png',
}

/**
 * Serve data/basemap at /basemap in dev, with HTTP Range support (PMTiles reads byte ranges).
 * Dev-only on purpose: the 1 GB extract must never be copied into a production build.
 */
function serveBasemap(): Plugin {
  return {
    name: 'serve-local-basemap',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/basemap', (req, res, next) => {
        const rel = decodeURIComponent((req.url ?? '/').split('?')[0])
        const file = path.resolve(BASEMAP_DIR, '.' + rel)
        if (!file.startsWith(BASEMAP_DIR + path.sep)) {
          res.statusCode = 403
          return res.end()
        }
        let size: number
        try {
          const st = statSync(file)
          if (!st.isFile()) return next()
          size = st.size
        } catch {
          res.statusCode = 404
          return res.end()
        }
        res.setHeader('Content-Type', MIME[path.extname(file)] ?? 'application/octet-stream')
        res.setHeader('Accept-Ranges', 'bytes')
        const range = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range ?? '')
        if (range) {
          const start = Number(range[1])
          const end = range[2] ? Math.min(Number(range[2]), size - 1) : size - 1
          if (start > end) {
            res.statusCode = 416
            res.setHeader('Content-Range', `bytes */${size}`)
            return res.end()
          }
          res.statusCode = 206
          res.setHeader('Content-Range', `bytes ${start}-${end}/${size}`)
          res.setHeader('Content-Length', end - start + 1)
          if (req.method === 'HEAD') return res.end()
          return createReadStream(file, { start, end }).pipe(res)
        }
        res.setHeader('Content-Length', size)
        if (req.method === 'HEAD') return res.end()
        createReadStream(file).pipe(res)
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), serveBasemap()],
  // MapLibre v6 loads its worker relative to its own module URL; pre-bundling into
  // .vite/deps breaks that path, so serve it straight from node_modules.
  optimizeDeps: { exclude: ['maplibre-gl'] },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
