import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { Profile } from '../me/roles'
import { UnitContext } from './UnitContext'

const STORAGE_KEY = 'watan-lms-active-unit'
const ALL_UNITS = 'all'

export function UnitProvider({
  profile,
  children,
}: {
  profile?: Profile
  children: ReactNode
}) {
  const [requestedValue, setRequestedValue] = useState(
    () => localStorage.getItem(STORAGE_KEY) ?? ALL_UNITS,
  )
  const unitsQuery = useQuery({
    queryKey: ['business-units', profile?.id],
    enabled: Boolean(profile),
    staleTime: 60_000,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/units')
      if (error) throw new Error('Unable to load business units.')
      if (!data) throw new Error('The server returned no business units.')
      return data.results
    },
  })

  const assignedUnitIds = useMemo(
    () => new Set(profile?.assignments.flatMap((assignment) => assignment.unit?.id ?? []) ?? []),
    [profile],
  )
  const units = useMemo(
    () => (unitsQuery.data ?? []).filter((unit) => profile?.is_global_read || assignedUnitIds.has(unit.id)),
    [assignedUnitIds, profile?.is_global_read, unitsQuery.data],
  )
  const canSelectUnit = Boolean(profile?.is_global_read || units.length > 1)

  const selectionReady = Boolean(profile && !unitsQuery.isPending && !unitsQuery.isError)
  const selectedValue = useMemo(() => {
    if (!selectionReady || !profile) return requestedValue
    if (profile.is_global_read) {
      return requestedValue === ALL_UNITS || units.some((unit) => unit.id === requestedValue)
        ? requestedValue
        : ALL_UNITS
    }
    if (units.length === 1) return units[0].id
    return units.some((unit) => unit.id === requestedValue)
      ? requestedValue
      : units[0]?.id ?? ALL_UNITS
  }, [profile, requestedValue, selectionReady, units])

  useEffect(() => {
    if (selectionReady) localStorage.setItem(STORAGE_KEY, selectedValue)
  }, [selectedValue, selectionReady])

  const selectUnit = (value: string) => {
    setRequestedValue(value)
    localStorage.setItem(STORAGE_KEY, value)
  }
  const unitId = selectedValue === ALL_UNITS ? undefined : selectedValue
  const unitLabel = selectedValue === ALL_UNITS
    ? profile?.is_global_read ? 'All units' : 'Your unit'
    : units.find((unit) => unit.id === selectedValue)?.name ?? 'Unit'

  return (
    <UnitContext.Provider
      value={{
        units,
        unitId,
        selectedValue,
        unitLabel,
        canSelectUnit,
        isLoading: unitsQuery.isPending,
        isError: unitsQuery.isError,
        selectUnit,
      }}
    >
      {children}
    </UnitContext.Provider>
  )
}
