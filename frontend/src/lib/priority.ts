/**
 * Display labels for the priority-topic categories (owner framework,
 * docs/framework/uxs-and-electricity-theft.md; ADR 0009). The categories are owner judgment;
 * what a record carries is what its source reported.
 */
export const CATEGORY_LABELS: Record<string, string> = {
  // UxS activity
  employment: 'Use',
  recovery_or_seizure: 'Recovery or seizure',
  procurement_or_import: 'Procurement or import',
  assembly_or_modification: 'Assembly or modification',
  training: 'Training',
  prosecution: 'Prosecution',
  // UxS platform
  suas_multirotor: 'Small multirotor',
  fpv: 'FPV',
  fixed_wing: 'Fixed wing',
  heavy_lift_or_hybrid: 'Heavy lift or hybrid',
  ugv: 'Ground robot (UGV)',
  usv: 'Uncrewed boat (USV)',
  unknown: 'Unknown',
  // UxS mission
  surveillance: 'Surveillance',
  route_security: 'Route security',
  overwatch: 'Overwatch',
  attack: 'Attack',
  logistics: 'Logistics',
  coercion_or_propaganda: 'Coercion or propaganda',
  surveillance_of_security_forces: 'Surveillance of security forces',
  monitoring_economic_activity: 'Monitoring economic activity',
  // UxS payload
  explosive_or_grenade: 'Explosive or grenade',
  ied: 'IED',
  camera_or_thermal: 'Camera or thermal',
  release_mechanism: 'Release mechanism',
  supply: 'Supply',
  loudspeaker_or_light: 'Loudspeaker or light',
  none_reported: 'None reported',
  // Electricity theft
  meter_bypass: 'Meter bypass',
  illegal_line_connection: 'Illegal line connection',
  transformer_or_feeder_tampering: 'Transformer or feeder tampering',
  insider_facilitation: 'Insider facilitation',
  crypto_mining: 'Crypto mining',
  cultivation: 'Cultivation',
  drug_lab: 'Drug lab',
  warehouse_or_storage: 'Warehouse or storage',
  refrigeration: 'Refrigeration',
  communications: 'Communications',
  residential_compound: 'Residential compound',
  other: 'Other',
  utility_employee: 'Utility employee',
  contractor: 'Contractor',
  electrician: 'Electrician',
  official: 'Official',
  property_manager: 'Property manager',
}

export const categoryLabel = (key: string): string =>
  CATEGORY_LABELS[key] ?? key.replaceAll('_', ' ')

export type Topic = 'uxs' | 'energy_theft'

export interface Period {
  key: string
  label: string
  days: number | null
}

export const PERIODS: Period[] = [
  { key: '90d', label: 'Last 90 days', days: 90 },
  { key: '1y', label: 'Last 12 months', days: 365 },
  { key: 'all', label: 'All reporting', days: null },
]

/** ISO start date for a period, or undefined for all reporting. */
export function periodStart(p: Period, today = new Date()): string | undefined {
  if (p.days === null) return undefined
  const d = new Date(today)
  d.setDate(d.getDate() - p.days)
  return d.toISOString().slice(0, 10)
}
