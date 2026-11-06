import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'
import { PageHeader } from '../app/PageHeader'
import { api } from '../api/client'
import type { components } from '../api/schema'
import {
  Badge,
  Button,
  Card,
  CardContent,
  DataTable,
  Drawer,
  EmptyState,
  ErrorState,
  FormField,
  Input,
  Select,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '../components/ui'
import type { DataTableColumn } from '../components/ui'
import { hasRole } from '../features/me/roles'
import { useMe } from '../features/me/useMe'
import { apiErrorMessage } from '../lib/apiError'
import { auth } from '../lib/firebase'
import { t } from '../lib/i18n'

type Invoice = components['schemas']['Invoice']
type Payment = components['schemas']['Payment']
type Student = components['schemas']['Student']
type FeeStructure = components['schemas']['FeeStructure']
type CashAccount = components['schemas']['CashAccount']

const invoiceFormSchema = z.object({
  student: z.string().uuid(t('Select a student.')),
  fee_structure: z.string().uuid(t('Select a fee structure.')),
  issue_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, t('Enter an issue date.')),
  due_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, t('Enter a due date.')),
}).refine((value) => value.due_date >= value.issue_date, {
  path: ['due_date'],
  message: t('The due date must be on or after the issue date.'),
})

const paymentFormSchema = z.object({
  invoice: z.string().uuid(t('Select an invoice.')),
  cash_account: z.string().uuid(t('Select a cash account.')),
  amount: z.string()
    .regex(/^\d+(\.\d{1,2})?$/, t('Enter an amount with up to two decimal places.'))
    .refine((value) => Number(value) > 0, t('The amount must be greater than zero.')),
  channel: z.enum(['CASH', 'MPESA_AGENT', 'BANK']),
  mpesa_code: z.string().optional(),
  payer_phone: z.string().optional(),
  received_at: z.string().min(1, t('Enter when the payment was received.')),
}).superRefine((value, context) => {
  if (value.channel === 'MPESA_AGENT' && !value.mpesa_code?.trim()) {
    context.addIssue({
      code: 'custom',
      path: ['mpesa_code'],
      message: t('Enter the M-Pesa transaction code.'),
    })
  }
})

type InvoiceFormValues = z.infer<typeof invoiceFormSchema>
type PaymentFormValues = z.infer<typeof paymentFormSchema>

const today = () => new Date().toISOString().slice(0, 10)

function localDateTime() {
  const date = new Date()
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().slice(0, 16)
}

function formatAmount(value: string) {
  return new Intl.NumberFormat(undefined, { minimumFractionDigits: 2 }).format(Number(value))
}

function formatDate(value: string) {
  return new Date(`${value.slice(0, 10)}T00:00:00`).toLocaleDateString()
}

async function downloadReceipt(payment: Payment) {
  const user = auth.currentUser
  if (!user) throw new Error(t('Sign in again before downloading this receipt.'))
  const token = await user.getIdToken()
  const url = new URL(payment.receipt.pdf_url, import.meta.env.VITE_API_URL || window.location.origin)
  const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || t('The receipt could not be downloaded.'))
  }

  const objectUrl = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = `receipt-${payment.receipt.number}.pdf`
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
}

export function Finance() {
  const { data: profile } = useMe()
  const queryClient = useQueryClient()
  const canManageFinance = hasRole(profile, 'SUPER_ADMIN', 'ADMIN', 'BURSAR', 'CASHIER')
  const isStudent = hasRole(profile, 'STUDENT')
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [ordering, setOrdering] = useState('-issue_date')
  const [paymentOrdering, setPaymentOrdering] = useState('-received_at')
  const [invoiceDrawerOpen, setInvoiceDrawerOpen] = useState(false)
  const [paymentDrawerOpen, setPaymentDrawerOpen] = useState(false)
  const [studentSearch, setStudentSearch] = useState('')
  const [feedback, setFeedback] = useState('')
  const [feedbackIsError, setFeedbackIsError] = useState(false)
  const [downloadingReceipt, setDownloadingReceipt] = useState<string | null>(null)
  const invoiceKey = useRef<{ fingerprint: string; key: string } | null>(null)
  const paymentKey = useRef<{ fingerprint: string; key: string } | null>(null)

  const invoiceQuery = useQuery({
    queryKey: ['finance', 'invoices', page, search, ordering],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/invoices/', {
        params: {
          query: {
            page,
            page_size: 20,
            search: search || undefined,
            ordering,
          },
        },
      })
      if (error) throw new Error(apiErrorMessage(error, t('Unable to load invoices.')))
      if (!data) throw new Error(t('The server returned no invoice data.'))
      return data
    },
  })

  const paymentQuery = useQuery({
    queryKey: ['finance', 'payments', page, paymentOrdering],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/payments/', {
        params: { query: { page, page_size: 20, ordering: paymentOrdering } },
      })
      if (error) throw new Error(apiErrorMessage(error, t('Unable to load payments.')))
      if (!data) throw new Error(t('The server returned no payment data.'))
      return data
    },
  })

  const studentsQuery = useQuery({
    queryKey: ['finance', 'students', studentSearch],
    enabled: canManageFinance && invoiceDrawerOpen,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/students/', {
        params: { query: { page_size: 20, search: studentSearch || undefined } },
      })
      if (error) throw new Error(apiErrorMessage(error, t('Unable to load students.')))
      if (!data) throw new Error(t('The server returned no student data.'))
      return data.results
    },
  })

  const feeStructuresQuery = useQuery({
    queryKey: ['finance', 'fee-structures'],
    enabled: canManageFinance && invoiceDrawerOpen,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/fee-structures/', {
        params: { query: { is_active: true, page_size: 100 } },
      })
      if (error) throw new Error(apiErrorMessage(error, t('Unable to load fee structures.')))
      if (!data) throw new Error(t('The server returned no fee-structure data.'))
      return data.results
    },
  })

  const cashAccountsQuery = useQuery({
    queryKey: ['finance', 'cash-accounts'],
    enabled: canManageFinance && paymentDrawerOpen,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/cash-accounts/', {
        params: { query: { is_active: true, page_size: 100 } },
      })
      if (error) throw new Error(apiErrorMessage(error, t('Unable to load cash accounts.')))
      if (!data) throw new Error(t('The server returned no cash-account data.'))
      return data.results
    },
  })

  const invoiceForm = useForm<InvoiceFormValues>({
    resolver: zodResolver(invoiceFormSchema),
    defaultValues: {
      student: '',
      fee_structure: '',
      issue_date: today(),
      due_date: today(),
    },
  })
  const paymentForm = useForm<PaymentFormValues>({
    resolver: zodResolver(paymentFormSchema),
    defaultValues: {
      invoice: '',
      cash_account: '',
      amount: '',
      channel: 'MPESA_AGENT',
      mpesa_code: '',
      payer_phone: '',
      received_at: localDateTime(),
    },
  })
  const paymentChannel = useWatch({
    control: paymentForm.control,
    name: 'channel',
  })

  const issueInvoice = useMutation({
    mutationFn: async (values: InvoiceFormValues) => {
      const fingerprint = JSON.stringify(values)
      if (invoiceKey.current?.fingerprint !== fingerprint) {
        invoiceKey.current = { fingerprint, key: crypto.randomUUID() }
      }
      const { data, error } = await api.POST('/api/v1/invoices/', {
        body: { ...values, idempotency_key: invoiceKey.current.key },
      })
      if (error) throw new Error(apiErrorMessage(error, t('The invoice could not be issued.')))
      if (!data) throw new Error(t('The server returned no invoice confirmation.'))
      return data
    },
    onSuccess: async (invoice) => {
      setFeedback(`${t('Invoice')} ${invoice.number} ${t('issued.')}`)
      setFeedbackIsError(false)
      setInvoiceDrawerOpen(false)
      invoiceKey.current = null
      invoiceForm.reset({ student: '', fee_structure: '', issue_date: today(), due_date: today() })
      await queryClient.invalidateQueries({ queryKey: ['finance'] })
    },
    onError: (error) => {
      setFeedback(error.message)
      setFeedbackIsError(true)
    },
  })

  const recordPayment = useMutation({
    mutationFn: async (values: PaymentFormValues) => {
      const { invoice, cash_account, amount, channel, mpesa_code, payer_phone, received_at } = values
      const fingerprint = JSON.stringify(values)
      if (paymentKey.current?.fingerprint !== fingerprint) {
        paymentKey.current = { fingerprint, key: crypto.randomUUID() }
      }
      const { data, error } = await api.POST('/api/v1/payments/', {
        body: {
          invoice,
          cash_account,
          amount,
          channel,
          mpesa_code: mpesa_code?.trim() || undefined,
          payer_phone: payer_phone?.trim() || '',
          received_at: new Date(received_at).toISOString(),
          idempotency_key: paymentKey.current.key,
        },
      })
      if (error) throw new Error(apiErrorMessage(error, t('The payment could not be recorded.')))
      if (!data) throw new Error(t('The server returned no payment confirmation.'))
      return data
    },
    onSuccess: async (payment) => {
      paymentKey.current = null
      setFeedback(`${t('Payment recorded.')} ${t('Receipt')} ${payment.receipt.number} ${t('is ready.')}`)
      setFeedbackIsError(false)
      setPaymentDrawerOpen(false)
      paymentForm.reset({
        invoice: '',
        cash_account: '',
        amount: '',
        channel: 'MPESA_AGENT',
        mpesa_code: '',
        payer_phone: '',
        received_at: localDateTime(),
      })
      await queryClient.invalidateQueries({ queryKey: ['finance'] })
    },
    onError: (error) => {
      setFeedback(error.message)
      setFeedbackIsError(true)
    },
  })

  const invoices = invoiceQuery.data?.results ?? []
  const payments = paymentQuery.data?.results ?? []
  const invoiceColumns: DataTableColumn<Invoice>[] = [
    { id: 'number', header: t('Invoice'), accessor: 'number', sortable: true },
    {
      id: 'student_name',
      header: t('Student'),
      cell: (invoice) => (
        <span>
          {invoice.student_name}
          <span className="block text-xs text-subtle">{invoice.student_registration_number}</span>
        </span>
      ),
    },
    { id: 'status', header: t('Status'), cell: (invoice) => <Badge variant={invoice.status === 'PAID' ? 'success' : invoice.status === 'VOID' ? 'neutral' : 'warning'}>{invoice.status}</Badge> },
    { id: 'amount', header: t('Amount'), cell: (invoice) => formatAmount(invoice.amount), sortable: true },
    { id: 'balance_due', header: t('Balance due'), cell: (invoice) => formatAmount(invoice.balance_due), sortable: true },
    { id: 'due_date', header: t('Due date'), cell: (invoice) => formatDate(invoice.due_date), sortable: true },
  ]
  const paymentColumns: DataTableColumn<Payment>[] = [
    { id: 'received_at', header: t('Received'), cell: (payment) => new Date(payment.received_at).toLocaleString(), sortable: true },
    {
      id: 'invoice_number',
      header: t('Invoice'),
      cell: (payment) => (
        <span>
          {payment.invoice_number}
          <span className="block text-xs text-subtle">{payment.student_name} · {payment.student_registration_number}</span>
        </span>
      ),
    },
    { id: 'channel', header: t('Channel'), cell: (payment) => payment.channel.replace('_', ' ') },
    { id: 'amount', header: t('Amount'), cell: (payment) => formatAmount(payment.amount), sortable: true },
    { id: 'receipt', header: t('Receipt'), cell: (payment) => (
      <Button
        variant="secondary"
        size="sm"
        loading={downloadingReceipt === payment.id}
        onClick={() => {
          setDownloadingReceipt(payment.id)
          setFeedback('')
          void downloadReceipt(payment)
            .then(() => {
              setFeedback(t('Receipt downloaded.'))
              setFeedbackIsError(false)
            })
            .catch((error: unknown) => {
              setFeedback(error instanceof Error ? error.message : t('The receipt could not be downloaded.'))
              setFeedbackIsError(true)
            })
            .finally(() => setDownloadingReceipt(null))
        }}
      >
        {t('Download PDF')}
      </Button>
    ) },
  ]

  return (
    <section className="space-y-5">
      <PageHeader
        title={isStudent ? t('My fees') : t('Finance workspace')}
        description={isStudent
          ? t('Review your invoices, balances, and payment receipts.')
          : t('Issue student invoices, record payments, and print receipts.')}
        actions={canManageFinance ? (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setInvoiceDrawerOpen(true)}>{t('Issue invoice')}</Button>
            <Button onClick={() => setPaymentDrawerOpen(true)}>{t('Record payment')}</Button>
          </div>
        ) : undefined}
      />

      {feedback && (
        <p className="rounded-md border border-line bg-surface p-3 text-sm" role={feedbackIsError ? 'alert' : 'status'}>
          {feedback}
        </p>
      )}

      <Card>
        <CardContent className="pt-5">
          <Tabs defaultValue="invoices" onValueChange={() => setPage(1)}>
            <TabsList aria-label={t('Finance records')}>
              <TabsTrigger value="invoices">{t('Invoices')}</TabsTrigger>
              <TabsTrigger value="payments">{t('Payments')}</TabsTrigger>
            </TabsList>
            <TabsContent value="invoices" className="space-y-4">
              <label className="block max-w-sm">
                <span className="mb-1 block text-sm font-medium">{t('Search invoices')}</span>
                <Input
                  value={search}
                  onChange={(event) => {
                    setSearch(event.target.value)
                    setPage(1)
                  }}
                  placeholder={t('Invoice number or student')}
                />
              </label>
              {invoiceQuery.isError ? (
                <ErrorState message={invoiceQuery.error.message} onRetry={() => void invoiceQuery.refetch()} />
              ) : (
                <DataTable
                  columns={invoiceColumns}
                  rows={invoices}
                  getRowId={(invoice) => invoice.id}
                  loading={invoiceQuery.isPending}
                  page={page}
                  pageSize={20}
                  total={invoiceQuery.data?.count ?? 0}
                  onPageChange={setPage}
                  onSortChange={(columnId, direction) => {
                    setOrdering(`${direction === 'desc' ? '-' : ''}${columnId}`)
                    setPage(1)
                  }}
                  emptyState={<EmptyState title={t('No invoices yet')} description={isStudent ? t('Your invoices will appear here when they are issued.') : t('Issue an invoice to get started.')} />}
                />
              )}
            </TabsContent>
            <TabsContent value="payments">
              {paymentQuery.isError ? (
                <ErrorState message={paymentQuery.error.message} onRetry={() => void paymentQuery.refetch()} />
              ) : (
                <DataTable
                  columns={paymentColumns}
                  rows={payments}
                  getRowId={(payment) => payment.id}
                  loading={paymentQuery.isPending}
                  page={page}
                  pageSize={20}
                  total={paymentQuery.data?.count ?? 0}
                  onPageChange={setPage}
                  onSortChange={(columnId, direction) => {
                    if (columnId === 'amount' || columnId === 'received_at') {
                      setPaymentOrdering(`${direction === 'desc' ? '-' : ''}${columnId}`)
                    }
                  }}
                  emptyState={<EmptyState title={t('No payments yet')} description={t('Recorded payments and their printable receipts will appear here.')} />}
                />
              )}
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <Drawer
        open={invoiceDrawerOpen}
        onOpenChange={setInvoiceDrawerOpen}
        title={t('Issue an invoice')}
        description={t('Select a student, fee structure, and invoice dates.')}
      >
        <form className="space-y-4" onSubmit={invoiceForm.handleSubmit((values) => issueInvoice.mutate(values))}>
          <FormField label={t('Find a student')}>
            <Input value={studentSearch} onChange={(event) => setStudentSearch(event.target.value)} placeholder={t('Search by name or registration number')} />
          </FormField>
          {studentsQuery.isError && <ErrorState message={studentsQuery.error.message} onRetry={() => void studentsQuery.refetch()} />}
          <FormField label={t('Student')} error={invoiceForm.formState.errors.student?.message}>
            <Select {...invoiceForm.register('student')} defaultValue="">
              <option value="" disabled>{studentsQuery.isPending ? t('Loading students…') : t('Select a student')}</option>
              {studentsQuery.data?.map((student: Student) => (
                <option key={student.id} value={student.id}>{student.registration_number} — {student.first_name} {student.last_name}</option>
              ))}
            </Select>
          </FormField>
          {feeStructuresQuery.isError && <ErrorState message={feeStructuresQuery.error.message} onRetry={() => void feeStructuresQuery.refetch()} />}
          <FormField label={t('Fee structure')} error={invoiceForm.formState.errors.fee_structure?.message}>
            <Select {...invoiceForm.register('fee_structure')} defaultValue="">
              <option value="" disabled>{feeStructuresQuery.isPending ? t('Loading fee structures…') : t('Select a fee structure')}</option>
              {feeStructuresQuery.data?.map((fee: FeeStructure) => (
                <option key={fee.id} value={fee.id}>{fee.code} — {fee.name} ({formatAmount(fee.amount)})</option>
              ))}
            </Select>
          </FormField>
          <FormField label={t('Issue date')} error={invoiceForm.formState.errors.issue_date?.message}>
            <Input type="date" {...invoiceForm.register('issue_date')} />
          </FormField>
          <FormField label={t('Due date')} error={invoiceForm.formState.errors.due_date?.message}>
            <Input type="date" {...invoiceForm.register('due_date')} />
          </FormField>
          <Button className="w-full" loading={issueInvoice.isPending} disabled={!studentsQuery.data?.length || !feeStructuresQuery.data?.length}>
            {t('Issue invoice')}
          </Button>
        </form>
      </Drawer>

      <Drawer
        open={paymentDrawerOpen}
        onOpenChange={setPaymentDrawerOpen}
        title={t('Record a payment')}
        description={t('Post a payment to an open invoice and issue its receipt.')}
      >
        <form className="space-y-4" onSubmit={paymentForm.handleSubmit((values) => recordPayment.mutate(values))}>
          {cashAccountsQuery.isError && <ErrorState message={cashAccountsQuery.error.message} onRetry={() => void cashAccountsQuery.refetch()} />}
          <FormField label={t('Invoice')} error={paymentForm.formState.errors.invoice?.message}>
            <Select {...paymentForm.register('invoice')} defaultValue="">
              <option value="" disabled>{invoiceQuery.isPending ? t('Loading invoices…') : t('Select an open invoice')}</option>
              {invoices.filter((invoice) => invoice.balance_due !== '0.00' && invoice.status !== 'VOID').map((invoice) => (
                <option key={invoice.id} value={invoice.id}>{invoice.number} — {invoice.student_name} — {formatAmount(invoice.balance_due)} due</option>
              ))}
            </Select>
          </FormField>
          <FormField label={t('Cash account')} error={paymentForm.formState.errors.cash_account?.message}>
            <Select {...paymentForm.register('cash_account')} defaultValue="">
              <option value="" disabled>{cashAccountsQuery.isPending ? t('Loading cash accounts…') : t('Select a cash account')}</option>
              {cashAccountsQuery.data?.map((account: CashAccount) => (
                <option key={account.id} value={account.id}>{account.name} ({account.kind.replace('_', ' ')})</option>
              ))}
            </Select>
          </FormField>
          <FormField label={t('Amount received')} error={paymentForm.formState.errors.amount?.message}>
            <Input inputMode="decimal" {...paymentForm.register('amount')} />
          </FormField>
          <FormField label={t('Payment channel')} error={paymentForm.formState.errors.channel?.message}>
            <Select {...paymentForm.register('channel')}>
              <option value="MPESA_AGENT">{t('M-Pesa agent')}</option>
              <option value="CASH">{t('Cash')}</option>
              <option value="BANK">{t('Bank')}</option>
            </Select>
          </FormField>
          {paymentChannel === 'MPESA_AGENT' && (
            <FormField label={t('M-Pesa transaction code')} error={paymentForm.formState.errors.mpesa_code?.message}>
              <Input {...paymentForm.register('mpesa_code')} />
            </FormField>
          )}
          <FormField label={t('Payer phone (optional)')} error={paymentForm.formState.errors.payer_phone?.message}>
            <Input type="tel" {...paymentForm.register('payer_phone')} />
          </FormField>
          <FormField label={t('Received at')} error={paymentForm.formState.errors.received_at?.message}>
            <Input type="datetime-local" {...paymentForm.register('received_at')} />
          </FormField>
          <Button className="w-full" loading={recordPayment.isPending} disabled={!cashAccountsQuery.data?.length || !invoices.some((invoice) => invoice.balance_due !== '0.00' && invoice.status !== 'VOID')}>
            {t('Record payment')}
          </Button>
        </form>
      </Drawer>
    </section>
  )
}
