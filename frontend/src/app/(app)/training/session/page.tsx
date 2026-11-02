'use client';

import { NotFoundState } from '@/components/ErrorState';
import { OrgGate } from '@/components/OrgGate';
import { WithQuery } from '@/components/WithQuery';
import { SessionView } from '@/components/training/SessionView';

export default function TrainingSessionPage() {
  return (
    <OrgGate permission="training.view">
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
                mode="admin"
                canCancel={m.permissions.includes('training.manage')}
                back={{ href: '/training/', label: 'Training' }}
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
