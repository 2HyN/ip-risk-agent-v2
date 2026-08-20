import { useIntegration } from "./integration-context";
import { Card, EmptyState, PageHeader } from "../shared/ui";

export function SourceSlotPage() {
  const integration = useIntegration();
  if (integration.sourcePanel !== undefined)
    return <>{integration.sourcePanel}</>;
  return (
    <div className="content">
      <PageHeader
        eyebrow="Source Plane integration"
        title="Connected sources"
        description="Provider connection and tracking controls are supplied by Agent 2 without changing Control Plane UI code."
      />
      <Card>
        <EmptyState
          title="Source UI slot is ready"
          description="Integration can inject the Agent 2 browser-safe source panel through the public ControlPlaneApp integration prop."
        />
      </Card>
    </div>
  );
}
