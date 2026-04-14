import { useEffect, useRef } from 'react'

interface GaugeProps {
  value: number
  min: number
  max: number
  label: string
  unit: string
  color?: string
  thresholds?: { warn: number; danger: number }
  size?: 'sm' | 'md' | 'lg'
}

export default function Gauge({
  value,
  min,
  max,
  label,
  unit,
  color = '#0ea5e9',
  thresholds,
  size = 'lg',
}: GaugeProps) {
  const animatedValue = useRef(0)
  const pathRef = useRef<SVGCircleElement>(null)

  const clampedValue = Math.min(Math.max(value, min), max)
  const percentage = ((clampedValue - min) / (max - min)) * 100

  // Determine color based on thresholds
  let activeColor = color
  if (thresholds) {
    const pct = percentage
    if (pct >= thresholds.danger) activeColor = '#ef4444'
    else if (pct >= thresholds.warn) activeColor = '#eab308'
    else activeColor = '#22c55e'
  }

  const dimensions = {
    sm: { svgSize: 100, radius: 36, stroke: 6, fontSize: 'text-lg', labelSize: 'text-[9px]' },
    md: { svgSize: 140, radius: 52, stroke: 7, fontSize: 'text-2xl', labelSize: 'text-[10px]' },
    lg: { svgSize: 180, radius: 68, stroke: 8, fontSize: 'text-3xl', labelSize: 'text-xs' },
  }

  const { svgSize, radius, stroke, fontSize, labelSize } = dimensions[size]
  const circumference = 2 * Math.PI * radius
  const arcLength = circumference * 0.75 // 270 degrees
  const offset = arcLength - (arcLength * percentage) / 100

  useEffect(() => {
    animatedValue.current = clampedValue
  }, [clampedValue])

  return (
    <div className="flex flex-col items-center">
      <div className="relative" style={{ width: svgSize, height: svgSize }}>
        <svg
          width={svgSize}
          height={svgSize}
          viewBox={`0 0 ${svgSize} ${svgSize}`}
          className="transform rotate-[135deg]"
        >
          {/* Background arc */}
          <circle
            cx={svgSize / 2}
            cy={svgSize / 2}
            r={radius}
            fill="none"
            stroke="#1e293b"
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${arcLength} ${circumference}`}
          />
          {/* Value arc */}
          <circle
            ref={pathRef}
            cx={svgSize / 2}
            cy={svgSize / 2}
            r={radius}
            fill="none"
            stroke={activeColor}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${arcLength} ${circumference}`}
            strokeDashoffset={offset}
            className="transition-all duration-500 ease-out"
            style={{
              filter: `drop-shadow(0 0 6px ${activeColor}50)`,
            }}
          />
        </svg>

        {/* Center value */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className={`font-mono font-bold ${fontSize} text-white tracking-tight`}
            style={{ textShadow: `0 0 20px ${activeColor}40` }}
          >
            {Math.round(clampedValue).toLocaleString()}
          </span>
          <span className={`font-mono ${labelSize} text-slate-500 -mt-1`}>{unit}</span>
        </div>
      </div>

      <span className="text-xs text-slate-400 font-medium mt-1 tracking-wide uppercase">
        {label}
      </span>
    </div>
  )
}
