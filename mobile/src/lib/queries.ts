import { QueryClient, useInfiniteQuery, useQuery } from '@tanstack/react-query';

import { ApiError } from '@/api/errors';
import type { TransactionDirection } from '@/api/types';
import { appConfig, auth, banks, investments, legal, loans, notifications, support, wallet } from '@/api/endpoints';

export const keys = {
  config: ['config'] as const,
  me: ['me'] as const,
  photo: (version: string | null | undefined) => ['photo', version ?? ''] as const,
  deletionCheck: ['deletion-check'] as const,
  sessions: ['sessions'] as const,
  products: ['products'] as const,
  applications: ['applications'] as const,
  application: (id: string) => ['applications', id] as const,
  loans: ['loans'] as const,
  loan: (id: string) => ['loans', id] as const,
  wallet: ['wallet'] as const,
  transactions: ['transactions'] as const,
  notifications: ['notifications'] as const,
  legal: (slug: string) => ['legal', slug] as const,
  legalList: ['legal'] as const,
  offer: (applicationId: string) => ['offer', applicationId] as const,
  faqs: ['faqs'] as const,
  tickets: ['tickets'] as const,
  ticket: (id: string) => ['tickets', id] as const,
  unread: ['notifications', 'unread'] as const,
  transactionList: (direction?: TransactionDirection) => ['transactions', 'list', direction ?? 'all'] as const,
  transaction: (id: string) => ['transactions', id] as const,
  banks: ['banks'] as const,
  investmentPlans: ['investments', 'plans'] as const,
  investments: ['investments', 'mine'] as const,
};

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 10 * 60_000,
        // Retry transient failures only; a 4xx won't fix itself.
        retry: (count, error) => count < 2 && (!(error instanceof ApiError) || error.status === 0 || error.status >= 500),
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
      },
      // Money-moving calls are never auto-retried; the user retries with the same idempotency key.
      mutations: { retry: false },
    },
  });
}

export const useAppConfig = () =>
  useQuery({ queryKey: keys.config, queryFn: appConfig, staleTime: 5 * 60_000, retry: 1 });

/** Features the server has switched on (loans is always on). */
export function useFeatures() {
  const { data } = useAppConfig();
  const f = (data?.features ?? {}) as Record<string, boolean>;
  return { wallet: !!f.wallet, investments: !!f.investments, support: data?.support };
}

export const useInvestmentPlans = () =>
  useQuery({ queryKey: keys.investmentPlans, queryFn: investments.plans, staleTime: 5 * 60_000 });
export const useMyInvestments = (enabled = true) =>
  useQuery({ queryKey: keys.investments, queryFn: investments.mine, enabled });

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: auth.me, staleTime: 5 * 60_000 });
/** The profile photo (chosen, else from the BVN record); refetched when `photo_version` changes. */
export const usePhoto = (version: string | null | undefined, enabled = true) =>
  useQuery({ queryKey: keys.photo(version), queryFn: auth.photo, staleTime: Infinity, enabled });
export const useDeletionCheck = () => useQuery({ queryKey: keys.deletionCheck, queryFn: auth.deletionCheck });
export const useSessions = () => useQuery({ queryKey: keys.sessions, queryFn: auth.sessions });
export const useProducts = () => useQuery({ queryKey: keys.products, queryFn: loans.products, staleTime: 10 * 60_000 });
export const useApplications = () =>
  useQuery({ queryKey: keys.applications, queryFn: () => loans.applications() });
export const useApplication = (id: string) =>
  useQuery({ queryKey: keys.application(id), queryFn: () => loans.application(id), enabled: !!id });
export const useLoans = () => useQuery({ queryKey: keys.loans, queryFn: loans.list });
export const useLoan = (id: string) => useQuery({ queryKey: keys.loan(id), queryFn: () => loans.detail(id), enabled: !!id });
/**
 * Always refetched on mount and app focus: money arrives by bank transfer outside the app,
 * and a stale balance would tell a customer who just paid in that they can't repay.
 */
export const useWallet = (enabled = true) =>
  useQuery({ queryKey: keys.wallet, queryFn: wallet.summary, enabled, staleTime: 0 });
export const useBanks = () => useQuery({ queryKey: keys.banks, queryFn: banks.list, staleTime: 6 * 3600_000 });

/** Wallet history, newest first, a page at a time (keyset cursor, so no repeats while scrolling). */
export const useTransactions = (direction?: TransactionDirection, enabled = true) =>
  useInfiniteQuery({
    queryKey: keys.transactionList(direction),
    queryFn: ({ pageParam }) => wallet.transactions({ direction, cursor: pageParam, limit: 20 }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled,
    staleTime: 0,
  });
export const useTransaction = (id: string) =>
  useQuery({ queryKey: keys.transaction(id), queryFn: () => wallet.transaction(id), enabled: !!id });

/** Inbox, newest first, 30 at a time. */
export const useNotifications = () =>
  useInfiniteQuery({
    queryKey: keys.notifications,
    queryFn: ({ pageParam }) => notifications.list(pageParam, 30),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined),
    staleTime: 0,
  });
/** Unread badge on the Home bell; refreshed on focus and whenever a push arrives. */
export const useUnreadCount = (enabled = true) =>
  useQuery({ queryKey: keys.unread, queryFn: notifications.unreadCount, enabled, staleTime: 30_000 });

export const useLegalDocuments = () =>
  useQuery({ queryKey: keys.legalList, queryFn: legal.list, staleTime: 10 * 60_000 });
export const useLegalDocument = (slug: string) =>
  useQuery({ queryKey: keys.legal(slug), queryFn: () => legal.document(slug), enabled: !!slug, staleTime: 10 * 60_000 });
export const useLoanOffer = (applicationId: string) =>
  useQuery({ queryKey: keys.offer(applicationId), queryFn: () => legal.offer(applicationId), enabled: !!applicationId, staleTime: 0 });
export const useFaqs = () => useQuery({ queryKey: keys.faqs, queryFn: support.faqs, staleTime: 30 * 60_000 });
export const useTickets = () => useQuery({ queryKey: keys.tickets, queryFn: support.tickets });
export const useTicket = (id: string) =>
  useQuery({ queryKey: keys.ticket(id), queryFn: () => support.ticket(id), enabled: !!id });
