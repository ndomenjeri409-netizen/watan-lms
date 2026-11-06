import { createContext } from 'react'
import type { components } from '../../api/schema'

export type BusinessUnit = components['schemas']['BusinessUnit']

export interface UnitContextValue {
  units: BusinessUnit[]
  unitId?: string
  selectedValue: string
  unitLabel: string
  canSelectUnit: boolean
  isLoading: boolean
  isError: boolean
  selectUnit: (value: string) => void
}

export const UnitContext = createContext<UnitContextValue | null>(null)
