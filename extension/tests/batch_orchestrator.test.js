const { describe, it, before, beforeEach } = require('node:test');
const assert = require('node:assert');

describe('BatchOrchestrator', () => {

  before(() => {
    globalThis.ApplywrightExtension = {};
    // Load the file under test
    require('../batch_orchestrator.js');
  });

  let orchestrator;

  beforeEach(() => {
    const { BatchOrchestrator } = globalThis.ApplywrightExtension;
    orchestrator = new BatchOrchestrator();
  });

  it('rejects loading an empty queue', () => {
    assert.throws(() => {
      orchestrator.loadQueue({ jobs: [] });
    }, /Queue is empty/);
  });

  it('rejects loading a queue larger than MAX_BATCH_SIZE', () => {
    const max = globalThis.ApplywrightExtension.MAX_BATCH_SIZE;
    const jobs = Array.from({ length: max + 1 }, (_, i) => ({
      external_id: `${1000 + i}`,
      job_url: `https://app.jobcopilot.com/applications/review/${1000 + i}`
    }));
    assert.throws(() => {
      orchestrator.loadQueue({ jobs });
    }, new RegExp(`Maximum batch size is ${max}`));
  });

  it('accepts a full-tracker-sized queue (415 jobs)', () => {
    const jobs = Array.from({ length: 415 }, (_, i) => ({
      external_id: `${2000 + i}`,
      job_url: `https://app.jobcopilot.com/applications/review/${2000 + i}`
    }));
    orchestrator.loadQueue({ jobs });
    assert.strictEqual(orchestrator.getState().queue.length, 415);
  });

  it('rejects non-numeric external_ids', () => {
    assert.throws(() => {
      orchestrator.loadQueue({ jobs: [{ external_id: '123a', job_url: 'https://app.jobcopilot.com/applications/review/123a' }] });
    }, /must contain digits only/);
  });

  it('rejects mismatched URLs', () => {
    assert.throws(() => {
      orchestrator.loadQueue({ jobs: [{ external_id: '123', job_url: 'https://app.jobcopilot.com/applications/review/456' }] });
    }, /Invalid URL for external_id/);
  });

  it('rejects duplicate external_ids', () => {
    assert.throws(() => {
      orchestrator.loadQueue({ jobs: [
        { external_id: '123', job_url: 'https://app.jobcopilot.com/applications/review/123' },
        { external_id: '123', job_url: 'https://app.jobcopilot.com/applications/review/123' }
      ] });
    }, /Duplicate external_id found/);
  });

  it('processes a valid queue sequentially', () => {
    orchestrator.loadQueue({ jobs: [
      { external_id: '101', job_url: 'https://app.jobcopilot.com/applications/review/101', title: 'Engineer' },
      { external_id: '102', job_url: 'https://app.jobcopilot.com/applications/review/102' }
    ]});

    orchestrator.start();
    assert.strictEqual(orchestrator.getState().status, 'running');

    let currentJob = orchestrator.getCurrentJob();
    assert.strictEqual(currentJob.external_id, '101');

    // Process first extraction
    orchestrator.processExtraction({
      jobs: [{
        external_id: '101',
        title: 'Engineer',
        job_url: 'https://app.jobcopilot.com/applications/review/101',
        description: 'A great job'
      }]
    });

    currentJob = orchestrator.getCurrentJob();
    assert.strictEqual(currentJob.external_id, '102');

    // Process second extraction
    orchestrator.processExtraction({
      jobs: [{
        external_id: '102',
        title: 'Manager',
        job_url: 'https://app.jobcopilot.com/applications/review/102',
        description: 'Another great job'
      }]
    });

    assert.strictEqual(orchestrator.getState().status, 'finished');
    assert.strictEqual(orchestrator.getState().extractedJobs.length, 2);
  });

  it('rejects extraction with mismatched external_id', () => {
    orchestrator.loadQueue({ jobs: [{ external_id: '101', job_url: 'https://app.jobcopilot.com/applications/review/101' }] });
    orchestrator.start();
    assert.throws(() => {
      orchestrator.processExtraction({ jobs: [{ external_id: '999', job_url: 'https://app.jobcopilot.com/applications/review/999', description: 'desc' }] });
    }, /Extracted external_id \(999\) does not match expected \(101\)/);
  });

  it('rejects extraction with missing description', () => {
    orchestrator.loadQueue({ jobs: [{ external_id: '101', job_url: 'https://app.jobcopilot.com/applications/review/101' }] });
    orchestrator.start();
    assert.throws(() => {
      orchestrator.processExtraction({ jobs: [{ external_id: '101', job_url: 'https://app.jobcopilot.com/applications/review/101', description: '  ' }] });
    }, /Extracted description is empty/);
  });

  it('rejects extraction with mismatched title or company', () => {
    orchestrator.loadQueue({ jobs: [{ external_id: '101', job_url: 'https://app.jobcopilot.com/applications/review/101', title: 'Developer', company: 'Acme' }] });
    orchestrator.start();
    assert.throws(() => {
      orchestrator.processExtraction({ jobs: [{ external_id: '101', title: 'Manager', company: 'Acme', description: 'desc', job_url: '...' }] });
    }, /Title mismatch/);
    
    assert.throws(() => {
      orchestrator.processExtraction({ jobs: [{ external_id: '101', title: 'Developer', company: 'Globex', description: 'desc', job_url: '...' }] });
    }, /Company mismatch/);
  });
  
  it('allows identical identities with different casing or non-alphanumerics', () => {
    orchestrator.loadQueue({ jobs: [{ external_id: '101', job_url: 'https://app.jobcopilot.com/applications/review/101', title: 'Sr. Developer', company: 'Acme Inc.' }] });
    orchestrator.start();
    orchestrator.processExtraction({ jobs: [{ external_id: '101', title: 'sr developer', company: 'acme inc', description: 'desc', job_url: '...' }] });
    assert.strictEqual(orchestrator.getState().extractedJobs.length, 1);
  });

  it('can generate an export payload', () => {
    orchestrator.loadQueue({ jobs: [{ external_id: '101', job_url: 'https://app.jobcopilot.com/applications/review/101' }] });
    orchestrator.start();
    orchestrator.processExtraction({ jobs: [{ external_id: '101', description: 'desc', application_status: 'applied' }] });
    
    const payload = orchestrator.generateExportPayload('1.0.0');
    assert.strictEqual(payload.metadata.export_kind, 'batch_enrichment');
    assert.strictEqual(payload.metadata.extension_version, '1.0.0');
    assert.strictEqual(payload.jobs.length, 1);
    
    // Check safety overrides
    assert.strictEqual(payload.jobs[0].application_status, 'saved');
    assert.strictEqual(payload.jobs[0].source, 'jobcopilot');
  });
  
  it('persists state correctly', () => {
    orchestrator.loadQueue({ jobs: [{ external_id: '101', job_url: 'https://app.jobcopilot.com/applications/review/101' }] });
    orchestrator.start();
    orchestrator.processExtraction({ jobs: [{ external_id: '101', description: 'desc' }] });
    
    const state = orchestrator.getState();
    const { BatchOrchestrator } = globalThis.ApplywrightExtension;
    const restored = new BatchOrchestrator(state);
    
    assert.strictEqual(restored.getState().status, 'finished');
    assert.strictEqual(restored.getState().extractedJobs[0].external_id, '101');
  });

});

// F1: the bridge rejects a batch_enrichment envelope of more than 20 jobs, so
// the exporter must never write a larger one.
describe('BatchOrchestrator export envelopes', () => {
  before(() => {
    if (!globalThis.ApplywrightExtension || !globalThis.ApplywrightExtension.BatchOrchestrator) {
      globalThis.ApplywrightExtension = {};
      delete require.cache[require.resolve('../batch_orchestrator.js')];
      require('../batch_orchestrator.js');
    }
  });

  function finishedBatch(count) {
    const { BatchOrchestrator } = globalThis.ApplywrightExtension;
    const orchestrator = new BatchOrchestrator();
    const jobs = Array.from({ length: count }, (_, i) => ({
      external_id: `${5000 + i}`,
      job_url: `https://app.jobcopilot.com/applications/review/${5000 + i}`
    }));
    orchestrator.loadQueue({ jobs });
    orchestrator.start();
    for (const job of jobs) {
      orchestrator.processExtraction({ jobs: [{ external_id: job.external_id, description: 'desc' }] });
    }
    return orchestrator;
  }

  it('splits 45 extracted jobs into envelopes of at most 20', () => {
    const payloads = finishedBatch(45).generateExportPayloads('1.0.0');
    assert.deepStrictEqual(payloads.map(p => p.jobs.length), [20, 20, 5]);
    for (const p of payloads) {
      assert.strictEqual(p.metadata.export_kind, 'batch_enrichment');
      assert.strictEqual(p.metadata.exported_count, p.jobs.length);
      assert.strictEqual(p.metadata.extension_version, '1.0.0');
    }
  });

  it('keeps every extracted job exactly once across envelopes', () => {
    const payloads = finishedBatch(45).generateExportPayloads();
    const ids = payloads.flatMap(p => p.jobs.map(j => j.external_id));
    assert.strictEqual(new Set(ids).size, 45);
  });

  it('returns one envelope for 20 jobs and none for zero jobs', () => {
    assert.strictEqual(finishedBatch(20).generateExportPayloads().length, 1);
    const { BatchOrchestrator } = globalThis.ApplywrightExtension;
    assert.deepStrictEqual(new BatchOrchestrator().generateExportPayloads(), []);
  });
});
