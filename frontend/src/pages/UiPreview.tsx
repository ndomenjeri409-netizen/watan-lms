import { useState } from 'react'
import { Check, Info, Plus, Search } from 'lucide-react'
import {
  Avatar,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
  Drawer,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  EmptyState,
  ErrorState,
  FormField,
  Input,
  Pagination,
  Select,
  Skeleton,
  StatCard,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
  useToast,
  type DataTableColumn,
} from '../components/ui'
import { getTheme, setTheme, type Theme } from '../lib/theme'

interface PreviewRow {
  id: string
  name: string
  status: string
}

const rows: PreviewRow[] = [
  { id: 'W-001', name: 'Amina Hassan', status: 'Active' },
  { id: 'W-002', name: 'Omar Ali', status: 'Pending' },
]

const columns: DataTableColumn<PreviewRow>[] = [
  { id: 'id', header: 'ID', accessor: 'id', sortable: true },
  { id: 'name', header: 'Name', accessor: 'name', sortable: true },
  { id: 'status', header: 'Status', cell: (row) => <Badge variant="success">{row.status}</Badge> },
]

export function UiPreview() {
  const [theme, setCurrentTheme] = useState<Theme>(getTheme)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedRows, setSelectedRows] = useState<PreviewRow[]>([])
  const { toast } = useToast()

  const changeTheme = (nextTheme: Theme) => {
    setTheme(nextTheme)
    setCurrentTheme(nextTheme)
  }

  return (
    <main className="mx-auto max-w-5xl space-y-8 p-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">UI primitives preview</h1>
          <p className="mt-1 text-sm text-subtle">Development-only component check for light and dark themes.</p>
        </div>
        <div className="flex gap-2" aria-label="Preview theme">
          <Button variant={theme === 'light' ? 'primary' : 'secondary'} size="sm" onClick={() => changeTheme('light')}>Light</Button>
          <Button variant={theme === 'dark' ? 'primary' : 'secondary'} size="sm" onClick={() => changeTheme('dark')}>Dark</Button>
        </div>
      </header>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Buttons, badges, avatar</h2>
        <div className="flex flex-wrap items-center gap-3">
          <Button><Plus size={16} aria-hidden="true" />Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Danger</Button>
          <Button loading>Loading</Button>
          <Button asChild variant="secondary"><a href="#cards">As child</a></Button>
          <Badge>Neutral</Badge>
          <Badge variant="success">Success</Badge>
          <Badge variant="warning">Warning</Badge>
          <Badge variant="danger">Danger</Badge>
          <Badge variant="info">Info</Badge>
          <Avatar alt="Amina Hassan" initials="AH" />
        </div>
      </section>

      <section id="cards" className="space-y-3">
        <h2 className="text-lg font-semibold">Cards and statistics</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Enrolled students" value={128} hint="Across all active courses" progress={72} trend={{ value: '8%', direction: 'up' }} />
          <StatCard label="Loading example" value="" loading />
          <StatCard label="Unavailable example" value="" error="Could not load this value." />
          <Card><CardHeader><CardTitle>Card title</CardTitle></CardHeader><CardContent>Card content area</CardContent></Card>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Form controls</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Search" hint="Search by name or student ID.">
            <Input placeholder="Search..." aria-label="Search" />
          </FormField>
          <FormField label="Status" error="Choose a valid status.">
            <Select defaultValue=""><option value="" disabled>Select status</option><option>Active</option><option>Pending</option></Select>
          </FormField>
          <FormField label="Notes">
            <Textarea placeholder="Add a note..." />
          </FormField>
          <div className="space-y-3">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-10 w-full" />
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Menus, tooltip, tabs</h2>
        <div className="flex flex-wrap items-center gap-4">
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="secondary">Open menu</Button></DropdownMenuTrigger>
            <DropdownMenuContent><DropdownMenuItem>Profile</DropdownMenuItem><DropdownMenuItem>Settings</DropdownMenuItem></DropdownMenuContent>
          </DropdownMenu>
          <Tooltip>
            <TooltipTrigger asChild><Button variant="ghost" aria-label="More information"><Info size={16} /></Button></TooltipTrigger>
            <TooltipContent>Extra information</TooltipContent>
          </Tooltip>
          <Button variant="secondary" onClick={() => toast({ title: 'Saved', description: 'Your changes were saved.', variant: 'success' })}>
            Show toast
          </Button>
          <Button variant="secondary" onClick={() => setDialogOpen(true)}>Open dialog</Button>
          <Button variant="secondary" onClick={() => setDrawerOpen(true)}>Open drawer</Button>
        </div>
        <Tabs defaultValue="overview">
          <TabsList aria-label="Preview sections">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="details">Details</TabsTrigger>
          </TabsList>
          <TabsContent value="overview">Overview tab content</TabsContent>
          <TabsContent value="details">Details tab content</TabsContent>
        </Tabs>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild><button className="sr-only">Dialog trigger</button></DialogTrigger>
          <DialogContent><DialogTitle>Preview dialog</DialogTitle><DialogDescription>Dialog with accessible focus handling.</DialogDescription></DialogContent>
        </Dialog>
        <Drawer open={drawerOpen} onOpenChange={setDrawerOpen} title="Create record" description="A side sheet for create and edit forms.">
          <div className="space-y-4">
            <FormField label="Name"><Input placeholder="Record name" /></FormField>
            <Button onClick={() => setDrawerOpen(false)}><Check size={16} />Save record</Button>
          </div>
        </Drawer>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">States and data table</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <EmptyState icon={<Search />} title="No matches found" description="Try adjusting your search." action={<Button variant="secondary" size="sm">Clear search</Button>} />
          <ErrorState message="The records could not be loaded." onRetry={() => toast({ title: 'Retry requested' })} />
        </div>
        <DataTable
          columns={columns}
          rows={rows}
          getRowId={(row) => row.id}
          page={1}
          pageSize={10}
          total={rows.length}
          onPageChange={() => undefined}
          onSortChange={(column, direction) => toast({ title: `Sort ${column}`, description: direction })}
          onSelectionChange={setSelectedRows}
          selectedRows={selectedRows}
          rowActions={() => [{ label: 'View record', onSelect: () => toast({ title: 'View record selected' }) }]}
        />
        <Pagination page={1} pageSize={10} total={24} onPageChange={() => undefined} />
      </section>
    </main>
  )
}
