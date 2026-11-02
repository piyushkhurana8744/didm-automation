'use client';

import { NotFoundState } from '@/components/ErrorState';
import { OrgGate } from '@/components/OrgGate';
import { WithQuery } from '@/components/WithQuery';
import { SessionView } from '@/components/training/SessionView';

export default function MySessionPage() {
  return (
    <OrgGate permission="training.self">
      {(m) => (
        <WithQuery>
          {(params) => {
            const id = params.get('id');
            return id ? (
              <SessionView
                key={id}
                orgId={m.organization.id}
                sessionId={id}
                permissions={m.permissions}
                mode="self"
                canCancel
                back={{ href: '/my-training/history/', label: 'My sessions' }}
              />
            ) : (
              <NotFoundState message="No session was chosen." />
            );
          }}
        </WithQuery>
      )}
    </OrgGate>
  );
}
