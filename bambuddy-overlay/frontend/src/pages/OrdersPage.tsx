import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ShoppingCart,
  Plus,
  Loader2,
  RefreshCw,
  Filter,
  X,
  ChevronRight,
  Package,
} from 'lucide-react';
import { useToast } from '../contexts/ToastContext';

const API_BASE = '/api/v1';

// ---------- types ----------------------------------------------------------

interface OrderListItem {
  id: number;
  marketplace: string;
  order_ref: string;
  buyer: string | null;
  status: string;
  received_at: string;
  item_count: number;
}

interface OrderCreate {
  marketplace: string;
  order_ref: string;
  buyer?: string;
  notes?: string;
}

// ---------- helpers --------------------------------------------------------

const STATUS_COLOURS: Record<string, string> = {
  new: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  allocated: 'bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300',
  printing: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300',
  printed: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
  shipped: 'bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300',
  cancelled: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400',
};

const MARKETPLACE_LABELS: Record<string, string> = {
  etsy: 'Etsy',
  ebay: 'eBay',
  amazon: 'Amazon',
  manual: 'Manual',
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLOURS[status] ?? 'bg-gray-100 text-gray-600'}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

// ---------- API calls -------------------------------------------------------

async function fetchOrders(status?: string, marketplace?: string): Promise<OrderListItem[]> {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (marketplace) params.set('marketplace', marketplace);
  const res = await fetch(`${API_BASE}/orders?${params}`, {
    headers: { Authorization: `Bearer ${sessionStorage.getItem('auth_token') ?? localStorage.getItem('auth_token') ?? ''}` },
  });
  if (!res.ok) throw new Error('Failed to load orders');
  return res.json();
}

async function createOrder(data: OrderCreate) {
  const res = await fetch(`${API_BASE}/orders`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${sessionStorage.getItem('auth_token') ?? localStorage.getItem('auth_token') ?? ''}`,
    },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail ?? 'Failed to create order');
  }
  return res.json();
}

async function updateOrderStatus(id: number, status: string) {
  const res = await fetch(`${API_BASE}/orders/${id}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${sessionStorage.getItem('auth_token') ?? localStorage.getItem('auth_token') ?? ''}`,
    },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error('Failed to update order');
  return res.json();
}

// ---------- New-order modal -------------------------------------------------

const MARKETPLACES = ['etsy', 'ebay', 'amazon', 'manual'];
const STATUSES = ['new', 'allocated', 'printing', 'printed', 'shipped', 'cancelled'];

function NewOrderModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [marketplace, setMarketplace] = useState('etsy');
  const [orderRef, setOrderRef] = useState('');
  const [buyer, setBuyer] = useState('');

  const mutation = useMutation({
    mutationFn: createOrder,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sf-orders'] });
      showToast('Order created', 'success');
      onClose();
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!orderRef.trim()) return;
    mutation.mutate({ marketplace, order_ref: orderRef.trim(), buyer: buyer.trim() || undefined });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full max-w-md mx-4 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">New Order</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X size={20} />
          </button>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Marketplace</label>
            <select
              value={marketplace}
              onChange={e => setMarketplace(e.target.value)}
              className="w-full border border-gray-300 dark:border-gray-700 rounded-md px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm"
            >
              {MARKETPLACES.map(m => (
                <option key={m} value={m}>{MARKETPLACE_LABELS[m] ?? m}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Order Reference *</label>
            <input
              required
              value={orderRef}
              onChange={e => setOrderRef(e.target.value)}
              placeholder="e.g. 1234567890"
              className="w-full border border-gray-300 dark:border-gray-700 rounded-md px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Buyer name</label>
            <input
              value={buyer}
              onChange={e => setBuyer(e.target.value)}
              placeholder="Optional"
              className="w-full border border-gray-300 dark:border-gray-700 rounded-md px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm"
            />
          </div>
          <div className="flex gap-2 justify-end pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm rounded-md border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800">
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="px-4 py-2 text-sm rounded-md bg-blue-600 hover:bg-blue-700 text-white font-medium disabled:opacity-50 flex items-center gap-2"
            >
              {mutation.isPending && <Loader2 size={14} className="animate-spin" />}
              Create Order
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------- Main page -------------------------------------------------------

export function OrdersPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [showNew, setShowNew] = useState(false);
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [filterMarketplace, setFilterMarketplace] = useState<string>('');

  const { data: orders, isLoading, error } = useQuery({
    queryKey: ['sf-orders', filterStatus, filterMarketplace],
    queryFn: () => fetchOrders(filterStatus || undefined, filterMarketplace || undefined),
    refetchInterval: 30_000,
  });

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => updateOrderStatus(id, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sf-orders'] });
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  });

  const hasFilters = filterStatus || filterMarketplace;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
        <div className="flex items-center gap-2">
          <ShoppingCart size={20} className="text-gray-600 dark:text-gray-400" />
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white">Orders</h1>
          {orders && (
            <span className="text-sm text-gray-500 dark:text-gray-400 ml-1">({orders.length})</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => queryClient.invalidateQueries({ queryKey: ['sf-orders'] })}
            className="p-2 rounded-md text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
            title="Refresh"
          >
            <RefreshCw size={16} />
          </button>
          <button
            onClick={() => setShowNew(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-md"
          >
            <Plus size={16} />
            New Order
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/50">
        <Filter size={14} className="text-gray-400 shrink-0" />
        <select
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value)}
          className="text-sm border border-gray-200 dark:border-gray-700 rounded px-2 py-1 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300"
        >
          <option value="">All statuses</option>
          {STATUSES.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
        </select>
        <select
          value={filterMarketplace}
          onChange={e => setFilterMarketplace(e.target.value)}
          className="text-sm border border-gray-200 dark:border-gray-700 rounded px-2 py-1 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300"
        >
          <option value="">All marketplaces</option>
          {MARKETPLACES.map(m => <option key={m} value={m}>{MARKETPLACE_LABELS[m]}</option>)}
        </select>
        {hasFilters && (
          <button
            onClick={() => { setFilterStatus(''); setFilterMarketplace(''); }}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
          >
            <X size={12} /> Clear
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {isLoading && (
          <div className="flex items-center justify-center h-48 gap-2 text-gray-500">
            <Loader2 size={20} className="animate-spin" />
            <span>Loading orders…</span>
          </div>
        )}

        {error && (
          <div className="m-4 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md text-red-700 dark:text-red-300 text-sm">
            Failed to load orders. Check backend connection.
          </div>
        )}

        {orders && orders.length === 0 && (
          <div className="flex flex-col items-center justify-center h-64 gap-3 text-gray-400">
            <Package size={40} className="opacity-40" />
            <p className="text-sm">{hasFilters ? 'No orders match the current filters' : 'No orders yet — create one to get started'}</p>
          </div>
        )}

        {orders && orders.length > 0 && (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
              <tr>
                <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-400">Order Ref</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-400">Marketplace</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-400">Buyer</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-400">Status</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-400">Items</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-400">Received</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {orders.map(order => (
                <tr key={order.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 group">
                  <td className="px-4 py-3 font-mono text-gray-900 dark:text-white font-medium">{order.order_ref}</td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{MARKETPLACE_LABELS[order.marketplace] ?? order.marketplace}</td>
                  <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{order.buyer ?? '—'}</td>
                  <td className="px-4 py-3">
                    <select
                      value={order.status}
                      onChange={e => statusMutation.mutate({ id: order.id, status: e.target.value })}
                      className="text-xs border-0 bg-transparent cursor-pointer focus:ring-0 p-0"
                      onClick={e => e.stopPropagation()}
                    >
                      {STATUSES.map(s => (
                        <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
                      ))}
                    </select>
                    <StatusBadge status={order.status} />
                  </td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{order.item_count}</td>
                  <td className="px-4 py-3 text-gray-500 dark:text-gray-400 whitespace-nowrap">{formatDate(order.received_at)}</td>
                  <td className="px-4 py-3 text-gray-400 opacity-0 group-hover:opacity-100">
                    <ChevronRight size={16} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showNew && <NewOrderModal onClose={() => setShowNew(false)} />}
    </div>
  );
}
