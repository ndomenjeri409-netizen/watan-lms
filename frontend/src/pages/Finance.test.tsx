import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { Finance } from './Finance'

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  profile: {
    id: 'student-user',
    role: 'STUDENT',
    assignments: [],
  } as { id: string; role: string; assignments: { role: string; unit: null }[] },
}))

vi.mock('../api/client', () => ({
  api: { GET: mocks.get, POST: mocks.post },
}))

vi.mock('../features/me/useMe', () => ({
  useMe: () => ({ data: mocks.profile }),
}))

vi.mock('../lib/firebase', () => ({
  auth: { currentUser: null },
}))

const invoice = {
  id: '7c31c36b-9007-49b0-8a8a-c1ff3d8e7507',
  number: 'INV-WTI-0001',
  student: '1c2a8966-973d-4c67-b02e-25d5af97c85d',
  student_name: 'Amina Njeri',
  student_registration_number: 'ICT-2026-0001',
  unit: 'be4f3fc2-7921-408c-a9de-b1d659ce9566',
  fee_structure: '26422eae-6e91-41ab-a12b-ff7592b0daee',
  issue_date: '2026-11-01',
  due_date: '2026-11-15',
  amount: '1000.00',
  balance_due: '500.00',
  status: 'PARTIAL',
  journal_entry: 'b6f89cc6-d8fa-4623-b44d-4aa3c65fc7be',
  created_at: '2026-11-01T10:00:00Z',
}

const student = {
  id: invoice.student,
  registration_number: 'ICT-2026-0001',
  first_name: 'Amina',
  last_name: 'Njeri',
}

const feeStructure = {
  id: invoice.fee_structure,
  code: 'TUITION',
  name: 'Tuition',
  amount: '1000.00',
}

const cashAccount = {
  id: '98bca23f-bf41-4f20-bc7f-7c55a0fd2869',
  name: 'WTI M-Pesa float',
  kind: 'MPESA_AGENT',
}

function renderFinance() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Finance />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Finance', () => {
  beforeEach(() => {
    mocks.profile = { id: 'student-user', role: 'STUDENT', assignments: [] }
    mocks.get.mockReset()
    mocks.post.mockReset()
    mocks.get.mockImplementation(async (path: string) => {
      const results = {
        '/api/v1/invoices/': [invoice],
        '/api/v1/payments/': [],
        '/api/v1/students/': [student],
        '/api/v1/fee-structures/': [feeStructure],
        '/api/v1/cash-accounts/': [cashAccount],
      }[path] ?? []
      return { data: { count: results.length, next: null, previous: null, results }, error: undefined }
    })
  })

  it('shows student-scoped invoices without finance write controls', async () => {
    renderFinance()

    expect(await screen.findByText('INV-WTI-0001')).toBeInTheDocument()
    expect(screen.getByText('Amina Njeri')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Issue invoice' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Record payment' })).not.toBeInTheDocument()
  })

  it('offers invoice and payment actions to bursars', async () => {
    mocks.profile = {
      id: 'bursar-user',
      role: 'BURSAR',
      assignments: [{ role: 'BURSAR', unit: null }],
    }
    renderFinance()

    expect(await screen.findByRole('button', { name: 'Issue invoice' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Record payment' })).toBeInTheDocument()
  })

  it('issues an invoice with the selected student and fee structure', async () => {
    mocks.profile = {
      id: 'bursar-user',
      role: 'BURSAR',
      assignments: [{ role: 'BURSAR', unit: null }],
    }
    mocks.post.mockResolvedValue({
      data: { ...invoice, number: 'INV-WTI-0002' },
      error: undefined,
    })
    renderFinance()

    await screen.findByText('INV-WTI-0001')
    fireEvent.click(screen.getByRole('button', { name: 'Issue invoice' }))
    await screen.findByRole('option', { name: /ICT-2026-0001/ })
    await screen.findByRole('option', { name: /TUITION — Tuition/ })
    fireEvent.change(screen.getByLabelText('Student'), { target: { value: student.id } })
    fireEvent.change(screen.getByLabelText('Fee structure'), { target: { value: feeStructure.id } })
    fireEvent.click(screen.getByRole('button', { name: 'Issue invoice' }))

    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith(
      '/api/v1/invoices/',
      expect.objectContaining({
        body: expect.objectContaining({
          student: student.id,
          fee_structure: feeStructure.id,
        }),
      }),
    ))
    expect(await screen.findByText('Invoice INV-WTI-0002 issued.')).toBeInTheDocument()
  })

  it('records an M-Pesa payment through the finance API', async () => {
    mocks.profile = {
      id: 'bursar-user',
      role: 'BURSAR',
      assignments: [{ role: 'BURSAR', unit: null }],
    }
    mocks.post.mockResolvedValue({
      data: {
        id: 'c567931c-89e2-41da-9fd8-50a6b0c1a8af',
        receipt: {
          id: 'e6832bc8-146b-4bbd-9812-28c399b7093b',
          number: 'RCT-WTI-001',
          pdf_url: '/api/v1/receipts/e6832bc8-146b-4bbd-9812-28c399b7093b/pdf/',
        },
      },
      error: undefined,
    })
    renderFinance()

    await screen.findByText('INV-WTI-0001')
    const submitButton = screen.getByRole('button', { name: 'Record payment' })
    expect(submitButton).not.toBeDisabled()
    fireEvent.click(submitButton)
    await screen.findByRole('option', { name: /INV-WTI-0001/ })
    await screen.findByRole('option', { name: /WTI M-Pesa float/ })
    fireEvent.change(await screen.findByLabelText('Invoice'), { target: { value: invoice.id } })
    fireEvent.change(screen.getByLabelText('Cash account'), { target: { value: cashAccount.id } })
    fireEvent.change(screen.getByLabelText('Amount received'), { target: { value: '100.00' } })
    fireEvent.change(screen.getByLabelText('M-Pesa transaction code'), { target: { value: 'QWE123' } })
    const formSubmit = screen.getByRole('button', { name: 'Record payment' })
    expect(formSubmit).not.toBeDisabled()
    fireEvent.click(formSubmit)
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith(
      '/api/v1/payments/',
      expect.objectContaining({
        body: expect.objectContaining({
          invoice: invoice.id,
          cash_account: cashAccount.id,
          amount: '100.00',
          channel: 'MPESA_AGENT',
          mpesa_code: 'QWE123',
          idempotency_key: expect.any(String),
        }),
      }),
    ))
    expect(await screen.findByText(/Payment recorded\./)).toBeInTheDocument()
  })
})
