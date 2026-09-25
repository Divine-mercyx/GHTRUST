import { QueryClient, useQuery } from '@tanstack/react-query';

import { ApiError } from '@/api/errors';
import { appConfig, auth, banks, loans, wallet } from '@/api/endpoints';

export const keys = {
  config: ['config'] as const,
  me: ['me'] as const,
  sessions: ['sessions'] as const,
  products: ['products'] as const,
  applications: ['applications'] as const,
  application: (id: string) => ['applications', id] as const,
  loans: ['loans'] as const,
  loan: (id: string) => ['loans', id] as const,
  wallet: ['wallet'] as const,
  banks: ['banks'] as const,
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
  return { wallet: !!f.wallet, support: data?.support };
}

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: auth.me, staleTime: 5 * 60_000 });
export const useSessions = () => useQuery({ queryKey: keys.sessions, queryFn: auth.sessions });
export const useProducts = () => useQuery({ queryKey: keys.products, queryFn: loans.products, staleTime: 10 * 60_000 });
export const useApplications = () =>
  useQuery({ queryKey: keys.applications, queryFn: () => loans.applications() });
export const useApplication = (id: string) =>
  useQuery({ queryKey: keys.application(id), queryFn: () => loans.application(id), enabled: !!id });
export const useLoans = () => useQuery({ queryKey: keys.loans, queryFn: loans.list });
export const useLoan = (id: string) => useQuery({ queryKey: keys.loan(id), queryFn: () => loans.detail(id), enabled: !!id });
export const useWallet = (enabled = true) => useQuery({ queryKey: keys.wallet, queryFn: wallet.summary, enabled });
export const useBanks = () => useQuery({ queryKey: keys.banks, queryFn: banks.list, staleTime: 6 * 3600_000 });
