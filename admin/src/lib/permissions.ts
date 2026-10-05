import type { StaffProfile } from './api'

export const PERMISSION_LABELS: Record<string, string> = {
  'staff:read': 'View staff',
  'staff:create': 'Create staff',
  'staff:update': 'Edit staff',
  'staff:activate': 'Activate / deactivate staff',
  'role:read': 'View roles',
  'role:create': 'Create roles',
  'role:update': 'Edit roles',
  'role:delete': 'Delete roles',
  'loan:read': 'View loans',
  'loan:review': 'Review applications',
  'loan:verify_documents': 'Verify documents',
  'loan:disburse': 'Disburse loans',
  'loan:configure_workflow': 'Configure workflows',
  'investment:read': 'View investments',
  'investment:manage': 'Manage investment plans',
}

export function permissionLabel(key: string): string {
  return PERMISSION_LABELS[key] ?? key
}

export function hasPermission(
  staff: StaffProfile | null | undefined,
  permission: string,
): boolean {
  if (!staff) return false
  if (staff.is_super_admin) return true
  return staff.permissions.includes(permission)
}

export function hasAnyPermission(
  staff: StaffProfile | null | undefined,
  permissions: string[],
): boolean {
  return permissions.some((p) => hasPermission(staff, p))
}
