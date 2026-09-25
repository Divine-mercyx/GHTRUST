import type { ScheduleItem } from '@/api/types';

/** The oldest installment not fully paid: what "next payment" means everywhere. */
export const nextInstallment = (schedule: ScheduleItem[]) => schedule.find((s) => s.status !== 'paid');
