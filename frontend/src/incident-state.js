export const actionBusy = (item) => ['approved', 'running', 'verifying'].includes(item?.action?.status);
export const watchActive = item => ['waiting', 'watching'].includes(item?.watch?.status);
export function incidentState(item, configured = true) {
  if (!item) return 'Loading';
  if (item.status === 'resolved') return item.action?.status === 'succeeded' ? 'Recovery verified' : 'Resolved';
  if (item.action?.status === 'verifying') return 'Verifying recovery';
  if (actionBusy(item)) return 'Rolling back';
  if (item.run_status === 'running') return 'Investigating';
  if (item.run_status === 'queued') return configured ? 'Queued for investigation' : 'Waiting for model';
  if (item.watch?.status === 'waiting') return 'Waiting for deployment';
  if (item.watch?.status === 'watching') return 'Monitoring deployment';
  if (item.watch?.status === 'passed') return 'Deployment checks passed';
  return 'Needs attention';
}
