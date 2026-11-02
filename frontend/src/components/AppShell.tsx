'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';
import { errorMessage } from '@/lib/api';
import { roleLabel } from '@/lib/roles';
import { useSession } from '@/lib/session';
import { Menu } from './Menu';
import { ACCOUNT_ITEMS, NAV_ITEMS, visibleItems, type NavItem } from './nav';

function normalize(path: string): string {
  return path.endsWith('/') ? path : `${path}/`;
}

/** The nav item for this page: an exact match, else the longest item that contains it (/agents/detail/ → Agents). */
function currentHref(items: NavItem[], pathname: string): string | null {
  const path = normalize(pathname);
  let best: string | null = null;
  for (const item of items) {
    if (path === item.href) return item.href;
    if (item.href !== '/' && path.startsWith(item.href) && (!best || item.href.length > best.length)) best = item.href;
  }
  return best;
}

function NavList({ items, pathname, label }: { items: NavItem[]; pathname: string; label: string }) {
  if (items.length === 0) return null;
  const currentItem = currentHref(items, pathname);
  return (
    <div className="nav-group">
      <p className="nav-group-label" aria-hidden="true">
        {label}
      </p>
      <ul>
        {items.map((item) => {
          const current = currentItem === item.href;
          return (
            <li key={item.href}>
              <Link href={item.href} className={current ? 'nav-link nav-link-current' : 'nav-link'} aria-current={current ? 'page' : undefined}>
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function OrgSwitcher() {
  const { me, activeMembership, switchOrg } = useSession();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const choices = me.memberships.filter((m) => m.organization.status === 'active');

  return (
    <div className="org-switcher">
      <Menu
        label={activeMembership ? `Organization: ${activeMembership.organization.name}. Switch organization` : 'Choose an organization'}
        align="start"
        buttonContent={<span className="truncate">{activeMembership ? activeMembership.organization.name : 'Choose organization'}</span>}
      >
        {(close) => (
          <ul className="menu-list">
            {choices.map((m) => {
              const current = m.organization.id === activeMembership?.organization.id;
              return (
                <li key={m.membership_id}>
                  <button
                    type="button"
                    className="menu-item"
                    aria-current={current ? 'true' : undefined}
                    onClick={async () => {
                      close();
                      setError(null);
                      if (current) return;
                      try {
                        await switchOrg(m.organization.id);
                        router.push('/dashboard/');
                      } catch (e) {
                        setError(errorMessage(e));
                      }
                    }}
                  >
                    <span className="truncate">{m.organization.name}</span>
                    <span className="menu-item-meta">{current ? 'Current' : roleLabel(m.role)}</span>
                  </button>
                </li>
              );
            })}
            {choices.length === 0 && <li className="menu-note">You are not in any active organization.</li>}
            <li className="menu-sep" role="separator" />
            <li>
              <Link href="/organizations/" className="menu-item" onClick={close}>
                All organizations
              </Link>
            </li>
          </ul>
        )}
      </Menu>
      {error && (
        <p className="header-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function UserMenu() {
  const { me, logout } = useSession();
  const [busy, setBusy] = useState(false);
  const display = me.user.name || me.user.email;
  return (
    <Menu label={`Account menu for ${display}`} buttonContent={<span className="truncate user-name">{display}</span>}>
      {(close) => (
        <ul className="menu-list">
          <li className="menu-note">
            Signed in as <strong className="break">{me.user.email}</strong>
          </li>
          <li>
            <Link href="/profile/" className="menu-item" onClick={close}>
              Profile
            </Link>
          </li>
          <li>
            <button
              type="button"
              className="menu-item"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                await logout();
              }}
            >
              {busy ? 'Logging out…' : 'Log out'}
            </button>
          </li>
        </ul>
      )}
    </Menu>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { me, activeMembership, permissions } = useSession();
  const pathname = usePathname() ?? '/';
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => setNavOpen(false), [pathname]);

  const opts = { hasOrg: !!activeMembership, permissions, isPlatformAdmin: me.user.is_platform_admin };
  const orgItems = visibleItems(NAV_ITEMS, opts);
  const accountItems = visibleItems(ACCOUNT_ITEMS, opts);

  return (
    <div className="shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <header className="header">
        <button
          type="button"
          className="nav-toggle"
          aria-expanded={navOpen}
          aria-controls="sidebar"
          onClick={() => setNavOpen((o) => !o)}
        >
          <span aria-hidden="true">☰</span>
          <span className="visually-hidden">{navOpen ? 'Close menu' : 'Open menu'}</span>
        </button>
        <Link href="/" className="brand">
          DIDM
        </Link>
        <OrgSwitcher />
        {activeMembership && <span className="role-badge">{roleLabel(activeMembership.role)}</span>}
        <div className="header-end">
          <UserMenu />
        </div>
      </header>
      <div className="shell-body">
        <nav id="sidebar" className={navOpen ? 'sidebar sidebar-open' : 'sidebar'} aria-label="Main">
          {activeMembership && [...new Set(orgItems.map((item) => item.group ?? 'Overview'))].map((group) => (
            <NavList key={group} items={orgItems.filter((item) => (item.group ?? 'Overview') === group)} pathname={pathname} label={group} />
          ))}
          <NavList items={accountItems} pathname={pathname} label="Account" />
        </nav>
        <main id="main" className="main" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
