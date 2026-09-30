import test from 'node:test';
import assert from 'node:assert/strict';
import {incidentState, actionBusy} from '../src/incident-state.js';

test('investigation completion means attention, not health', () => {
  assert.equal(incidentState({status:'active', run_status:'running'}), 'Investigating');
  assert.equal(incidentState({status:'active', run_status:'completed'}), 'Needs attention');
  assert.equal(incidentState({status:'active', run_status:'failed'}), 'Needs attention');
});
test('recovery is green only after the executor verifies it', () => {
  assert.equal(incidentState({status:'active', action:{status:'running'}}), 'Rolling back');
  assert.equal(incidentState({status:'active', action:{status:'verifying'}}), 'Verifying recovery');
  assert.equal(incidentState({status:'active', action:{status:'failed'}}), 'Needs attention');
  assert.equal(incidentState({status:'resolved', action:{status:'succeeded'}}), 'Recovery verified');
  assert.equal(incidentState({status:'resolved'}), 'Closed');
  assert.equal(actionBusy({action:{status:'approved'}}), true);
});
