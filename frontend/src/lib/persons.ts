/** Labels for person roles and claims (ADR 0013). Everything shown is "as reported". */
export const PERSON_ROLE_LABELS: Record<string, string> = {
  leader: 'Leader',
  member: 'Member',
  facilitator: 'Facilitator',
  operator_or_technician: 'Operator or technician',
  supplier: 'Supplier',
  front_business_owner: 'Front-business owner',
  financier: 'Financier',
  complicit_official: 'Official reported as complicit',
  associate: 'Associate',
  // event roles
  perpetrator: 'Perpetrator',
  directed: 'Directed',
  arrested: 'Arrested',
  charged: 'Charged',
  convicted: 'Convicted',
  sentenced: 'Sentenced',
  convicted_or_sentenced: 'Convicted or sentenced',
  extradited: 'Extradited',
  killed: 'Killed',
  escaped: 'Escaped',
  fugitive: 'Fugitive',
  released: 'Released',
  designated: 'Designated',
}

export const CLAIM_KIND_LABELS: Record<string, string> = {
  role: 'Reported role',
  alias: 'Alias',
  nationality: 'Nationality',
  status: 'Status',
  title: 'Rank or post',
  organization: 'Organization link',
  event: 'Event link',
}

export const roleLabel = (key: string) => PERSON_ROLE_LABELS[key] ?? key.replaceAll('_', ' ')
