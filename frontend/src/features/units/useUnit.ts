import { useContext } from 'react'
import { UnitContext } from './UnitContext'

export function useUnit() {
  const context = useContext(UnitContext)
  if (!context) throw new Error('useUnit must be used within a UnitProvider.')
  return context
}
