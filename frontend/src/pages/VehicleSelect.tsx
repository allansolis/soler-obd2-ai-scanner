import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Car, ChevronRight, Search, Zap } from 'lucide-react'

// Base de datos resumida de vehiculos soportados (de vehicle_maps_db.py)
const VEHICLE_DATABASE = {
  'Chevrolet': {
    'S10': ['2012-2015 EDC16C39'],
    'Tracker': ['2000-2015 2.0'],
  },
  'Fiat': {
    'Ducato': ['2008-2015 2.3 MJD_8F3', '2000-2008 2.8 JTD', '2009-2018 Cargo 2.3'],
    'Toro': ['2016-2020 HW0281031204'],
  },
  'Ford': {
    'Focus': ['2015-2020 MED17.8.2'],
    'Ranger': ['2012-2020 2.2 SID208', '2013-2020 3.2 ATM SID208', '2006-2012 3.0D SID901C'],
  },
  'GM': {
    'Prisma': ['2013-2020 1.0 FJNX'],
    'S10': ['2012-2020 2.8 Diesel'],
  },
  'Hyundai': {
    'HR': ['2013-2020 2.5 DCM 3.7 Delphi'],
  },
  'Iveco': {
    'Daily': ['2014-2020 EDC17CP52', '2011-2014 EDC17CP54'],
    'Euro Cargo': ['2005-2015 Tector'],
  },
  'Kia': {
    'Bongo': ['2013-2020 DC3.5 2.5BT'],
  },
  'Mercedes-Benz': {
    'C280': ['2008 3.0L V6 M272 (ME9.7)'],
    'Sprinter': ['2012-2020 415 DCM3.5'],
    '1620': ['2010-2018'],
    '2644': ['2010-2018'],
    'Accelo': ['2015-2020'],
    'Actros': ['2008-2020'],
  },
  'Mitsubishi': {
    'L200 Triton': ['2007-2015 3.2'],
    'Pajero': ['2007-2015 3.2TD', '2000-2007 3.2TD'],
  },
  'Nissan': {
    'Frontier': ['2013-2020 2.3', '2015-2020 190CV ATM', '2003-2012 2.5'],
  },
  'Peugeot': {
    'Partner': ['2008-2018'],
  },
  'Renault': {
    'Master': ['2003-2013 2.5', '2005-2015 2.8'],
  },
  'Scania': {
    'G380': ['2008-2015 EMS S6'],
    'G420': ['2008-2015 EMS S6'],
  },
  'Toyota': {
    'Hilux': ['2005-2015 2.5/3.0 D4D'],
    'Land Cruiser Prado': ['1996-2002 3.0D', '1996-2002 3.4D'],
  },
  'Volvo': {
    'VM 270': ['2010-2020 MAP PACK REMOÇÃO ARLA'],
    'VM': ['2010-2020 6.5/4.8/7.2'],
  },
  'VW': {
    'Amarok': ['2010-2020 EDC17C54', '2010-2020 EDC17CP20'],
    'Constellation': ['2008-2018 17.250'],
  },
  'BMW': {
    '330i': ['2018-2020 MEVD17'],
    '530i': ['2017-2020 MEVD17'],
  },
  'Honda': {
    'Civic': ['2016-2021 1.5T', '2020-2024 2.0'],
  },
  'Mazda': {
    'Mazda6': ['2004 2.3L L3 (Denso 275800)'],
    'Mazda3': ['2014-2019 Skyactiv-G'],
    'CX-5': ['2013-2020 Skyactiv-D'],
  },
}

type Step = 'brand' | 'model' | 'version' | 'confirm'

export default function VehicleSelect() {
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>('brand')
  const [selectedBrand, setSelectedBrand] = useState<string>('')
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [selectedVersion, setSelectedVersion] = useState<string>('')
  const [search, setSearch] = useState('')

  const brands = Object.keys(VEHICLE_DATABASE).sort()
  const filteredBrands = brands.filter(b =>
    b.toLowerCase().includes(search.toLowerCase())
  )

  const handleBrandClick = (brand: string) => {
    setSelectedBrand(brand)
    setStep('model')
    setSearch('')
  }

  const handleModelClick = (model: string) => {
    setSelectedModel(model)
    setStep('version')
  }

  const handleVersionClick = (version: string) => {
    setSelectedVersion(version)
    setStep('confirm')
  }

  const handleConnect = () => {
    // Guardar seleccion y navegar a dashboard
    localStorage.setItem('soler-vehicle', JSON.stringify({
      brand: selectedBrand,
      model: selectedModel,
      version: selectedVersion,
      connectedAt: new Date().toISOString()
    }))
    navigate('/')
  }

  const handleBack = () => {
    if (step === 'version') setStep('model')
    else if (step === 'model') setStep('brand')
    else if (step === 'confirm') setStep('version')
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-semibold text-slate-100 mb-1">
          Seleccionar Vehiculo
        </h1>
        <p className="text-sm text-slate-400">
          Elige tu vehiculo para conectar el agente AI con el modelo correcto
        </p>
      </div>

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 mb-6 text-sm">
        <span className={step === 'brand' ? 'text-obd-accent font-medium' : 'text-slate-500'}>
          1. Marca
        </span>
        <ChevronRight className="w-4 h-4 text-slate-600" />
        <span className={step === 'model' ? 'text-obd-accent font-medium' : selectedBrand ? 'text-slate-400' : 'text-slate-600'}>
          2. Modelo {selectedBrand && `(${selectedBrand})`}
        </span>
        <ChevronRight className="w-4 h-4 text-slate-600" />
        <span className={step === 'version' ? 'text-obd-accent font-medium' : selectedModel ? 'text-slate-400' : 'text-slate-600'}>
          3. Version {selectedModel && `(${selectedModel})`}
        </span>
        <ChevronRight className="w-4 h-4 text-slate-600" />
        <span className={step === 'confirm' ? 'text-obd-accent font-medium' : 'text-slate-600'}>
          4. Confirmar
        </span>
      </div>

      {/* Search bar (solo brand step) */}
      {step === 'brand' && (
        <div className="relative mb-6">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Buscar marca..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-3 bg-obd-surface border border-obd-border rounded-xl text-slate-200 placeholder-slate-500 focus:outline-none focus:border-obd-accent transition-colors"
          />
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {step === 'brand' && (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {filteredBrands.map(brand => (
              <button
                key={brand}
                onClick={() => handleBrandClick(brand)}
                className="p-5 bg-obd-surface border border-obd-border rounded-xl hover:border-obd-accent/60 hover:bg-obd-accent/5 transition-all text-left group"
              >
                <Car className="w-6 h-6 text-obd-accent mb-3 group-hover:scale-110 transition-transform" />
                <div className="font-medium text-slate-200">{brand}</div>
                <div className="text-xs text-slate-500 mt-1">
                  {Object.keys(VEHICLE_DATABASE[brand as keyof typeof VEHICLE_DATABASE]).length} modelos
                </div>
              </button>
            ))}
          </div>
        )}

        {step === 'model' && selectedBrand && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {Object.keys(VEHICLE_DATABASE[selectedBrand as keyof typeof VEHICLE_DATABASE]).map(model => (
              <button
                key={model}
                onClick={() => handleModelClick(model)}
                className="p-5 bg-obd-surface border border-obd-border rounded-xl hover:border-obd-accent/60 hover:bg-obd-accent/5 transition-all text-left"
              >
                <div className="font-medium text-slate-200">{model}</div>
                <div className="text-xs text-slate-500 mt-1">
                  {(VEHICLE_DATABASE[selectedBrand as keyof typeof VEHICLE_DATABASE] as Record<string, string[]>)[model].length} version(es)
                </div>
              </button>
            ))}
          </div>
        )}

        {step === 'version' && selectedBrand && selectedModel && (
          <div className="grid grid-cols-1 gap-3">
            {((VEHICLE_DATABASE[selectedBrand as keyof typeof VEHICLE_DATABASE] as Record<string, string[]>)[selectedModel]).map(version => (
              <button
                key={version}
                onClick={() => handleVersionClick(version)}
                className="p-4 bg-obd-surface border border-obd-border rounded-xl hover:border-obd-accent/60 hover:bg-obd-accent/5 transition-all text-left flex items-center justify-between"
              >
                <div>
                  <div className="font-medium text-slate-200">{version}</div>
                  <div className="text-xs text-slate-500 mt-1">
                    {selectedBrand} {selectedModel}
                  </div>
                </div>
                <ChevronRight className="w-5 h-5 text-slate-500" />
              </button>
            ))}
          </div>
        )}

        {step === 'confirm' && (
          <div className="max-w-2xl mx-auto">
            <div className="bg-gradient-to-br from-obd-accent/10 to-purple-500/10 border border-obd-accent/30 rounded-2xl p-8 mb-6">
              <Zap className="w-10 h-10 text-obd-accent mb-4" />
              <h2 className="text-2xl font-semibold text-slate-100 mb-4">
                Listo para conectar
              </h2>
              <div className="space-y-3 mb-6">
                <div className="flex justify-between py-2 border-b border-obd-border">
                  <span className="text-slate-400">Marca</span>
                  <span className="text-slate-100 font-medium">{selectedBrand}</span>
                </div>
                <div className="flex justify-between py-2 border-b border-obd-border">
                  <span className="text-slate-400">Modelo</span>
                  <span className="text-slate-100 font-medium">{selectedModel}</span>
                </div>
                <div className="flex justify-between py-2 border-b border-obd-border">
                  <span className="text-slate-400">Version / ECU</span>
                  <span className="text-slate-100 font-medium">{selectedVersion}</span>
                </div>
              </div>

              <div className="bg-obd-surface/50 rounded-lg p-4 mb-6 border border-amber-500/20">
                <div className="text-xs font-semibold text-amber-400 mb-2">
                  ⚠ PROTOCOLO DE SEGURIDAD
                </div>
                <ul className="space-y-1.5 text-sm text-slate-300">
                  <li>✓ El agente AI cargara el perfil especifico de este vehiculo</li>
                  <li>✓ Se ajustaran los umbrales a los rangos normales de este motor</li>
                  <li>✓ Antes de cualquier modificacion ECU se hara backup triple verificado</li>
                  <li>✓ El sistema bloquea modificaciones si hay DTCs criticos</li>
                </ul>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={handleConnect}
                  className="flex-1 py-3 bg-obd-accent hover:bg-obd-accent/90 text-white font-semibold rounded-xl transition-colors"
                >
                  Conectar con este vehiculo
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Back button */}
      {step !== 'brand' && (
        <div className="mt-4 flex">
          <button
            onClick={handleBack}
            className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
          >
            ← Atras
          </button>
        </div>
      )}
    </div>
  )
}
