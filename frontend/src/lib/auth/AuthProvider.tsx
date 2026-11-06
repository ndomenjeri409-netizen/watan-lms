import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signOut,
  type User,
} from 'firebase/auth'
import { auth } from '../firebase'
import { AuthContext, type AuthContextValue } from './auth-context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [firebaseUser, setFirebaseUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => onAuthStateChanged(auth, (user) => {
    setFirebaseUser(user)
    setLoading(false)
  }), [])

  const value = useMemo<AuthContextValue>(() => ({
    firebaseUser,
    loading,
    async login(email, password) {
      await signInWithEmailAndPassword(auth, email, password)
    },
    async logout() {
      await signOut(auth)
    },
  }), [firebaseUser, loading])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
