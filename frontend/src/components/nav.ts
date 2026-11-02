import type { Permission } from '@/lib/types';

export interface NavItem {
  href: string;
  label: string;
  /** Hidden unless the active membership has this permission. */
  permission?: Permission;
  /** Hidden unless the user is a platform administrator. */
  platformAdmin?: boolean;
  /** One line used in the dashboard's "What's here" list. */
  blurb: string;
  group?: 'Overview' | 'People' | 'AI Training' | 'Insights' | 'Settings';
}

export const NAV_ITEMS: NavItem[] = [
  { href: '/my-training/', label: 'My AI coaches', permission: 'training.self', group: 'Overview', blurb: 'Voice agents assigned to you and their scenarios.' },
  { href: '/my-training/history/', label: 'My practice sessions', permission: 'training.self', group: 'Overview', blurb: 'Your practice sessions and how they went.' },
  { href: '/my-training/progress/', label: 'My progress', permission: 'training.self', group: 'Overview', blurb: 'Your scores, skills and feedback over time.' },
  { href: '/dashboard/', label: 'Overview', permission: 'org.view', group: 'Overview', blurb: 'Your organization at a glance.' },
  { href: '/users/', label: 'Trainees & trainers', permission: 'members.view', group: 'People', blurb: 'People in this organization and their roles.' },
  { href: '/invitations/', label: 'Invitations', permission: 'invitations.manage', group: 'People', blurb: 'Invite people and manage pending invitations.' },
  { href: '/teams/', label: 'Teams', permission: 'teams.view', group: 'People', blurb: 'Groups of people you can assign agents to together.' },
  { href: '/agents/', label: 'Agents', permission: 'agents.view', group: 'AI Training', blurb: 'Registered voice agents, their versions and scenarios.' },
  { href: '/knowledge/', label: 'Knowledge library', permission: 'knowledge.view', group: 'AI Training', blurb: 'Approved facts, FAQs and document revisions for AI agents.' },
  { href: '/assignments/', label: 'Assignments', permission: 'assignments.manage', group: 'AI Training', blurb: 'Give people and teams access to agents.' },
  { href: '/training/', label: 'Sessions & evaluations', permission: 'training.view', group: 'AI Training', blurb: 'Practice sessions, usage and limits for the organization.' },
  { href: '/rubrics/', label: 'Evaluation rubrics', permission: 'training.view', group: 'AI Training', blurb: 'How practice sessions are scored.' },
  { href: '/training/phones/', label: 'Verified phones', permission: 'training.manage', group: 'AI Training', blurb: 'Verify the numbers trainees practise on.' },
  { href: '/settings/', label: 'Organization settings', permission: 'org.update', group: 'Settings', blurb: 'Organization name and details.' },
  { href: '/settings/audit/', label: 'Audit log', permission: 'audit.view', group: 'Settings', blurb: 'A record of changes made in this organization.' },
];

export const ACCOUNT_ITEMS: NavItem[] = [
  { href: '/organizations/', label: 'Organizations', blurb: 'Switch between organizations you belong to.' },
  { href: '/profile/', label: 'Profile', blurb: 'Your name, phone number and password.' },
  { href: '/platform/', label: 'Platform admin', platformAdmin: true, blurb: 'Create and suspend organizations, and set their training limits.' },
];

export function visibleItems(items: NavItem[], opts: { hasOrg: boolean; permissions: Permission[]; isPlatformAdmin: boolean }): NavItem[] {
  return items.filter((item) => {
    if (item.platformAdmin && !opts.isPlatformAdmin) return false;
    if (item.permission && (!opts.hasOrg || !opts.permissions.includes(item.permission))) return false;
    return true;
  });
}
