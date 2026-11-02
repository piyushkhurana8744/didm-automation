import type { Role } from './types';

export const ROLES: Role[] = ['organization_owner', 'organization_admin', 'trainer', 'trainee'];

const LABELS: Record<Role, string> = {
  organization_owner: 'Owner',
  organization_admin: 'Admin',
  trainer: 'Trainer',
  trainee: 'Trainee',
};

export function roleLabel(role: string): string {
  return (LABELS as Record<string, string>)[role] ?? role.replace(/_/g, ' ');
}

/** Mirrors the backend: owners grant any role; admins grant admin, trainer and trainee. */
export function grantableRoles(actor: Role | undefined): Role[] {
  if (actor === 'organization_owner') return ROLES;
  if (actor === 'organization_admin') return ROLES.filter((r) => r !== 'organization_owner');
  return [];
}

/** Mirrors the backend: owners manage anyone; admins cannot change or remove owners. */
export function canManageMember(actor: Role | undefined, target: Role): boolean {
  if (actor === 'organization_owner') return true;
  return actor === 'organization_admin' && target !== 'organization_owner';
}
