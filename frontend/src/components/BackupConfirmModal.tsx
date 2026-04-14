import { useState } from 'react'
import { ShieldCheck, AlertTriangle, Loader2, CheckCircle2, X } from 'lucide-react'

type Step = 'confirm' | 'reading' | 'hashing' | 'saving' | 'verifying' | 'done' | 'error'

interface BackupConfirmModalProps {
  vehicle: { brand: string; model: string; version: string } | null
  profileName: string
  onCancel: () => void
  onConfirm: () => void
}

export default function BackupConfirmModal({
  vehicle,
  profileName,
  onCancel,
  onConfirm,
}: BackupConfirmModalProps) {
  const [step, setStep] = useState<Step>('confirm')
  const [backupId, setBackupId] = useState('')
  const [hash, setHash] = useState('')

  const startBackup = async () => {
    // Simulacion del flujo de backup
    setStep('reading')
    await new Promise(r => setTimeout(r, 1200))

    setStep('hashing')
    const mockHash = Array.from({ length: 12 }, () =>
      '0123456789abcdef'[Math.floor(Math.random() * 16)]
    ).join('')
    setHash(mockHash)
    await new Promise(r => setTimeout(r, 800))

    setStep('saving')
    await new Promise(r => setTimeout(r, 900))

    setStep('verifying')
    await new Promise(r => setTimeout(r, 1100))

    const id = `${vehicle?.brand.toUpperCase().slice(0, 3)}_${Date.now().toString(36)}`
    setBackupId(id)
    setStep('done')
  }

  const handleProceed = () => {
    onConfirm()
  }

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-6">
      <div className="bg-obd-surface border border-obd-border rounded-2xl max-w-xl w-full overflow-hidden">
        {/* Header */}
        <div className="p-6 border-b border-obd-border flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-obd-accent/15 flex items-center justify-center">
              <ShieldCheck className="w-5 h-5 text-obd-accent" />
            </div>
            <div>
              <div className="text-lg font-semibold text-slate-100">
                Backup obligatorio antes de modificar
              </div>
              <div className="text-xs text-slate-400">
                Protocolo de seguridad SOLER
              </div>
            </div>
          </div>
          {(step === 'confirm' || step === 'done' || step === 'error') && (
            <button
              onClick={onCancel}
              className="text-slate-400 hover:text-slate-200 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Body */}
        <div className="p-6">
          {step === 'confirm' && (
            <>
              <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-4 mb-5">
                <div className="flex gap-3">
                  <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
                  <div className="text-sm text-amber-100">
                    <strong>IMPORTANTE:</strong> Se hara un backup completo de la
                    calibracion actual de tu ECU antes de aplicar el perfil{' '}
                    <strong className="text-amber-300">{profileName}</strong>. Este
                    backup permite restaurar el estado original en cualquier
                    momento.
                  </div>
                </div>
              </div>

              <div className="space-y-2 mb-5">
                <div className="text-xs font-semibold text-slate-400 uppercase mb-2">
                  El backup incluye:
                </div>
                {[
                  'Dump binario completo de la ECU',
                  'Hash SHA-256 para verificar integridad',
                  'Manifest con VIN, marca, modelo, version ECU',
                  'Timestamp preciso del momento del backup',
                  'Almacenamiento en data/backups/{VIN}/{timestamp}/',
                ].map(item => (
                  <div key={item} className="flex items-center gap-2 text-sm text-slate-300">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <span>{item}</span>
                  </div>
                ))}
              </div>

              {vehicle && (
                <div className="bg-obd-bg/50 rounded-lg p-3 mb-5 text-sm">
                  <div className="text-xs text-slate-500 mb-1">Vehiculo objetivo</div>
                  <div className="text-slate-200">
                    {vehicle.brand} {vehicle.model} — {vehicle.version}
                  </div>
                </div>
              )}

              <div className="flex gap-3">
                <button
                  onClick={onCancel}
                  className="flex-1 py-3 border border-obd-border text-slate-300 rounded-xl hover:bg-obd-bg/50 transition-colors"
                >
                  Cancelar
                </button>
                <button
                  onClick={startBackup}
                  className="flex-1 py-3 bg-obd-accent hover:bg-obd-accent/90 text-white font-semibold rounded-xl transition-colors"
                >
                  Iniciar backup
                </button>
              </div>
            </>
          )}

          {(step === 'reading' || step === 'hashing' || step === 'saving' || step === 'verifying') && (
            <div className="space-y-3 py-6">
              {[
                { key: 'reading', label: '1. Leyendo calibracion ECU...', size: '2.1 MB' },
                { key: 'hashing', label: '2. Calculando hash SHA-256...', hash },
                { key: 'saving', label: '3. Guardando backup local...' },
                { key: 'verifying', label: '4. Verificando integridad...' },
              ].map(item => {
                const stepOrder = ['reading', 'hashing', 'saving', 'verifying']
                const currentIdx = stepOrder.indexOf(step)
                const itemIdx = stepOrder.indexOf(item.key)
                const isDone = itemIdx < currentIdx
                const isActive = item.key === step
                const isPending = itemIdx > currentIdx

                return (
                  <div
                    key={item.key}
                    className={`flex items-center gap-3 p-3 rounded-lg border ${
                      isActive
                        ? 'bg-obd-accent/10 border-obd-accent/40'
                        : isDone
                        ? 'bg-emerald-500/5 border-emerald-500/20'
                        : 'bg-obd-bg/30 border-obd-border/50'
                    }`}
                  >
                    {isDone ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                    ) : isActive ? (
                      <Loader2 className="w-5 h-5 text-obd-accent animate-spin" />
                    ) : (
                      <div className="w-5 h-5 rounded-full border border-slate-600" />
                    )}
                    <div className="flex-1">
                      <div className={`text-sm ${isPending ? 'text-slate-500' : 'text-slate-200'}`}>
                        {item.label}
                      </div>
                      {item.size && isActive && (
                        <div className="text-xs text-slate-400 mt-0.5">{item.size}</div>
                      )}
                      {item.hash && (isActive || isDone) && (
                        <div className="text-xs text-obd-accent font-mono mt-0.5">
                          {hash}...
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {step === 'done' && (
            <>
              <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-lg p-4 mb-5 text-center">
                <CheckCircle2 className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
                <div className="text-lg font-semibold text-emerald-100 mb-1">
                  Backup completado y verificado
                </div>
                <div className="text-xs text-emerald-300/80">
                  El sistema puede ahora aplicar cambios de forma segura
                </div>
              </div>

              <div className="space-y-2 mb-5 text-sm">
                <div className="flex justify-between py-2 border-b border-obd-border">
                  <span className="text-slate-400">Backup ID</span>
                  <span className="text-slate-100 font-mono">{backupId}</span>
                </div>
                <div className="flex justify-between py-2 border-b border-obd-border">
                  <span className="text-slate-400">Hash SHA-256</span>
                  <span className="text-obd-accent font-mono text-xs">
                    {hash}...
                  </span>
                </div>
                <div className="flex justify-between py-2 border-b border-obd-border">
                  <span className="text-slate-400">Tamano</span>
                  <span className="text-slate-100">2.1 MB</span>
                </div>
                <div className="flex justify-between py-2">
                  <span className="text-slate-400">Estado</span>
                  <span className="text-emerald-400 font-medium">Verificado ✓</span>
                </div>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={onCancel}
                  className="flex-1 py-3 border border-obd-border text-slate-300 rounded-xl hover:bg-obd-bg/50 transition-colors"
                >
                  Solo backup (no aplicar)
                </button>
                <button
                  onClick={handleProceed}
                  className="flex-1 py-3 bg-obd-accent hover:bg-obd-accent/90 text-white font-semibold rounded-xl transition-colors"
                >
                  Aplicar perfil {profileName}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
