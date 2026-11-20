# Owner framework: unmanned systems and electricity theft

> UNCLASSIFIED — OPEN-SOURCE INFORMATION ONLY
>
> **Owner judgment, not sourced fact (CLAUDE.md rule 2).** This framework condenses the owner's working notes ("UxS Power", 2026-11-13). It shapes prompts, PIRs, categories and scoring. Nothing here is stored or shown as a finding. Records come only from cited sources.

The system collects, normalizes, classifies, deduplicates, enriches and alerts. It does not make final attribution decisions.

## 1. Unmanned systems (UxS)

### Working assessment
- **Platforms:**
  - TCO capability is mainly commercial and modular: commercial small drones (sUAS, such as DJI Mavic and Matrice or Autel EVO) and improvised FPV drones.
  - Ground (UGV) and maritime (USV) systems are less mature, but cost and technical barriers are falling.
- **Acquisition:** most systems are bought through licit or gray-market channels and adapted locally. Direct foreign state assistance is less likely than indirect knowledge transfer and commercial training.
- **Missions:**
  - surveillance and force protection dominate day-to-day use;
  - the low-cost aerial explosive carrier is the highest-threat use;
  - the value of cheap FPV drones is growing because they need little infrastructure.
- **Indicators:** the most reliable indicators combine several things: procurement anomalies, trained operators, battery and charging infrastructure, recurring flight patterns, and links to TCO locations. The aircraft alone is a weak indicator.
- **Escalation ladder** (not every group climbs it, and the simplest rungs already produce effects):
  1. observation drones
  2. thermal reconnaissance
  3. FPV and low-level flight
  4. payload drops
  5. one-way attacks
  6. coordinated multi-drone operations
  7. relays and repeaters
  8. more advanced autonomy

### Categories used in extraction
| Dimension | Values |
|---|---|
| Platform | `suas_multirotor`, `fpv`, `fixed_wing`, `heavy_lift_or_hybrid`, `ugv`, `usv`, `unknown` |
| Mission | `surveillance`, `route_security`, `overwatch`, `attack`, `logistics`, `coercion_or_propaganda`, `surveillance_of_security_forces`*, `monitoring_economic_activity` |
| Payload | `explosive_or_grenade`, `ied`, `camera_or_thermal`, `release_mechanism`, `supply`, `loudspeaker_or_light`, `none_reported` |
| Activity | `employment`, `recovery_or_seizure`, `procurement_or_import`, `assembly_or_modification`, `training`, `prosecution` |

\* Rule 4 applies: record what the TCO did and the location at the source's precision. Never record units, positions or the response.

### PIRs
1. Which cartels are using UxS, and for what missions?
2. Are groups moving from commercial camera drones to FPV or weaponized systems?
3. What countries, suppliers or marketplaces are associated with procurement?
4. Where are training and assembly sites reported?
5. Which individuals or entities are reported as providing technical knowledge, parts or instruction?
6. Are groups using UxS in coordinated attacks, route security or area surveillance?
7. Are there signs of more advanced autonomy, networking, relays or multi-system operations?

## 2. Electricity theft

### Working assessment
- **Why TCOs steal power:** to cut operating costs, hide revenue-generating activity, and feed sites with large or irregular loads:
  - cannabis and other controlled-environment cultivation
  - cryptocurrency mining
  - illicit production or storage
  - compounds that hide intensive loads
- **National context:** the commonly cited figure for Mexico's electricity losses is about 10–15%, most of it non-technical and urban. Theft attributable to TCOs is a small, hard-to-measure subset of that.
- **Scale:** sites range from tens of kW (small grows or mining rigs) through hundreds of kW (warehouses) to megawatts (large sites or networks of sites).
- **Location alone proves nothing.** What matters is a site showing power, facility and behavioral anomalies together.

### Scope limit
The notes also describe how investigators find suspect sites: utility-account anomalies, feeder data, thermal screening, network traffic, and ranking facilities by mismatch. The dashboard does **not** do this. It needs non-public utility data (rule 1), and it would flag specific private properties by inference. The dashboard tracks **reported** cases: raids, investigations, prosecutions and CFE or official statements.

### Categories used in extraction
| Dimension | Values |
|---|---|
| Method | `meter_bypass`, `illegal_line_connection`, `transformer_or_feeder_tampering`, `insider_facilitation`, `unknown` |
| Powered activity | `crypto_mining`, `cultivation`, `drug_lab`, `warehouse_or_storage`, `refrigeration`, `communications`, `residential_compound`, `other` |
| Facilitator (as reported) | `utility_employee`, `contractor`, `electrician`, `official`, `property_manager`, `none_reported` |
| Scale (as reported) | the source's kW, MW or equipment count, never estimated |

### PIRs
1. Which criminal organizations or facilitators are implicated in electricity theft?
2. What methods are used to bypass or manipulate electrical infrastructure?
3. What types of facilities are being powered?
4. Is the theft linked to crypto mining, cultivation, illicit manufacturing or logistics?
5. Are utility workers, contractors, officials or businesses reported as facilitating it?
6. What is the geographic concentration and operational scale?
7. Are methods becoming more sophisticated or more widespread?

## 3. Search taxonomy (Spanish and English)
These terms drive GDELT and search-API queries and the local filter.

- **UxS:**
  - dron, drones, vehículo aéreo no tripulado, aeronave no tripulada, sistema no tripulado
  - UAS, UAV, FPV, cuadricóptero, hexacóptero
  - dron artesanal, dron modificado, dron armado, dron explosivo
  - drone, unmanned system, unmanned aircraft, loitering munition, remote-controlled aircraft
- **Criminal context:**
  - cártel, cartel, organización criminal, grupo criminal, célula
  - sicarios, halcones, vigilancia, convoy, emboscada, ataque aéreo
  - explosivo, atentado, frontera, laboratorio, campamento, ruta, plaza
  - tráfico, contrabando, secuestro, extorsión, vigilancia aérea
- **Procurement and training:**
  - importación, decomiso, aseguramiento, compra, adquisición, proveedor
  - piezas, componentes, baterías, motores, controlador, circuito
  - armado, ensamblaje, capacitación, entrenamiento, operador, técnico
  - electrónica, soldadura, taller, proveedores extranjeros, instructor extranjero
- **Energy theft:**
  - robo de energía, robo de luz, electricidad clandestina, conexión clandestina
  - diablito, alteración de medidor, bypass, medidor manipulado
  - toma ilegal, conexión ilegal, transformador, cableado clandestino, infraestructura eléctrica
- **Utility context:**
  - CFE, Comisión Federal de Electricidad, tarifa, acometida, subestación, alimentador
  - red eléctrica, baja/media/alta tensión, carga eléctrica, consumo irregular
  - reconexión, fraude energético
- **Activities powered by theft:**
  - minería de criptomonedas, bitcoin, criptomonedas, granja de minería
  - centro de datos, servidor, cultivo indoor, invernadero
  - laboratorio clandestino, refrigeración, almacén
  - planta clandestina, producción ilegal, manufactura ilícita
- **Facilitation:**
  - corrupción, soborno, empleado de CFE, contratista, funcionario
  - complicidad, intermediario, facilitador
  - empresa fantasma, prestanombre, empresa de fachada
