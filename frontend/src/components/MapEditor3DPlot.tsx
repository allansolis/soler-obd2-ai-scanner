import { useEffect, useRef, useState } from 'react'

interface Props {
  data: number[][]
  xAxis: number[]
  yAxis: number[]
  min: number
  max: number
}

// Lightweight canvas-based 3D surface renderer (isometric projection)
export default function MapEditor3DPlot({ data, xAxis, yAxis, min, max }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [rotation, setRotation] = useState({ x: 0.6, y: 0.4 })
  const drag = useRef<{ startX: number; startY: number; rx: number; ry: number } | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const W = canvas.width
    const H = canvas.height
    ctx.fillStyle = '#020817'
    ctx.fillRect(0, 0, W, H)

    const rows = data.length
    const cols = data[0]?.length ?? 0
    if (!rows || !cols) return

    const cx = W / 2
    const cy = H / 2 + 60
    const scale = Math.min(W, H) * 0.55
    const range = max - min || 1

    const cosY = Math.cos(rotation.y)
    const sinY = Math.sin(rotation.y)
    const cosX = Math.cos(rotation.x)
    const sinX = Math.sin(rotation.x)

    const project = (ix: number, iy: number, v: number) => {
      const x = (ix / (cols - 1) - 0.5) * scale
      const y = (iy / (rows - 1) - 0.5) * scale
      const z = -((v - min) / range - 0.5) * scale * 0.6

      const x1 = x * cosY - y * sinY
      const y1 = x * sinY + y * cosY
      const y2 = y1 * cosX - z * sinX
      const z2 = y1 * sinX + z * cosX

      return { x: cx + x1, y: cy + y2, depth: z2 }
    }

    const colorFor = (v: number) => {
      const t = Math.max(0, Math.min(1, (v - min) / range))
      const r = Math.floor(20 + t * 235)
      const g = Math.floor(100 + (1 - Math.abs(t - 0.5) * 2) * 155)
      const b = Math.floor(255 - t * 230)
      return `rgba(${r},${g},${b},0.85)`
    }

    // Draw quads back-to-front
    const quads: Array<{ pts: any[]; depth: number; v: number }> = []
    for (let y = 0; y < rows - 1; y++) {
      for (let x = 0; x < cols - 1; x++) {
        const p1 = project(x, y, data[y][x])
        const p2 = project(x + 1, y, data[y][x + 1])
        const p3 = project(x + 1, y + 1, data[y + 1][x + 1])
        const p4 = project(x, y + 1, data[y + 1][x])
        const avgV = (data[y][x] + data[y][x + 1] + data[y + 1][x + 1] + data[y + 1][x]) / 4
        const depth = (p1.depth + p2.depth + p3.depth + p4.depth) / 4
        quads.push({ pts: [p1, p2, p3, p4], depth, v: avgV })
      }
    }
    quads.sort((a, b) => b.depth - a.depth)

    for (const q of quads) {
      ctx.beginPath()
      ctx.moveTo(q.pts[0].x, q.pts[0].y)
      for (let i = 1; i < 4; i++) ctx.lineTo(q.pts[i].x, q.pts[i].y)
      ctx.closePath()
      ctx.fillStyle = colorFor(q.v)
      ctx.fill()
      ctx.strokeStyle = 'rgba(14,165,233,0.25)'
      ctx.lineWidth = 0.5
      ctx.stroke()
    }

    // Axis labels
    ctx.fillStyle = '#64748b'
    ctx.font = '11px JetBrains Mono, monospace'
    ctx.fillText(`X: RPM (${xAxis[0]} - ${xAxis[xAxis.length - 1]})`, 12, H - 30)
    ctx.fillText(`Y: Carga (${yAxis[0]} - ${yAxis[yAxis.length - 1]}%)`, 12, H - 14)
    ctx.fillText(`Z: Valor (${min.toFixed(1)} - ${max.toFixed(1)})`, W - 200, H - 14)
  }, [data, xAxis, yAxis, min, max, rotation])

  return (
    <div
      className="relative w-full h-full flex items-center justify-center bg-obd-bg rounded-lg border border-obd-border overflow-hidden select-none"
      onMouseDown={(e) => {
        drag.current = { startX: e.clientX, startY: e.clientY, rx: rotation.x, ry: rotation.y }
      }}
      onMouseMove={(e) => {
        if (!drag.current) return
        const dx = e.clientX - drag.current.startX
        const dy = e.clientY - drag.current.startY
        setRotation({
          x: drag.current.rx + dy * 0.005,
          y: drag.current.ry + dx * 0.005,
        })
      }}
      onMouseUp={() => (drag.current = null)}
      onMouseLeave={() => (drag.current = null)}
    >
      <canvas ref={canvasRef} width={800} height={500} className="cursor-move max-w-full max-h-full" />
      <div className="absolute top-2 right-2 text-[10px] text-slate-500 font-mono bg-obd-surface/80 px-2 py-1 rounded">
        Arrastra para rotar
      </div>
    </div>
  )
}
