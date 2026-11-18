globalThis.ApplywrightExtension = globalThis.ApplywrightExtension || {};

// Upper bound on a single enrichment run. The orchestrator persists state and
// supports Resume Batch, so long runs are expected; this guard only exists to
// reject absurd payloads.
globalThis.ApplywrightExtension.MAX_BATCH_SIZE = 500;

// The bridge rejects a batch_enrichment envelope of more than 20 jobs
// (applywright json_import.py). Nothing on the bridge side splits a
// larger envelope, so generateExportPayloads() splits the result here.
globalThis.ApplywrightExtension.MAX_ENVELOPE_JOBS = 20;

globalThis.ApplywrightExtension.BatchOrchestrator = class BatchOrchestrator {
  constructor(state = null) {
    if (state) {
      this.state = JSON.parse(JSON.stringify(state));
    } else {
      this.state = {
        status: 'idle', // idle, running, stopped, finished
        queue: [],
        currentIndex: 0,
        extractedJobs: [],
        failed: [],
        batch_started_at: null,
        batch_finished_at: null,
        stopped_reason: null,
        last_successful_external_id: null
      };
    }
  }

  getState() {
    return this.state;
  }

  loadQueue(payload) {
    if (this.state.status === 'running') {
      throw new Error("Cannot load queue while batch is running");
    }

    if (!payload || !Array.isArray(payload.jobs)) {
      throw new Error("Invalid queue format: expected { jobs: [...] }");
    }

    const jobs = payload.jobs;
    if (jobs.length === 0) {
      throw new Error("Queue is empty");
    }
    const maxBatch = globalThis.ApplywrightExtension.MAX_BATCH_SIZE;
    if (jobs.length > maxBatch) {
      throw new Error(`Maximum batch size is ${maxBatch}`);
    }

    const seenIds = new Set();
    const validatedQueue = [];

    for (const job of jobs) {
      if (!job.external_id || typeof job.external_id !== 'string' || !/^\d+$/.test(job.external_id)) {
        throw new Error(`Invalid external_id: ${job.external_id} (must contain digits only)`);
      }
      
      const expectedUrl = `https://app.jobcopilot.com/applications/review/${job.external_id}`;
      if (job.job_url !== expectedUrl) {
        throw new Error(`Invalid URL for external_id ${job.external_id}: expected ${expectedUrl}`);
      }

      if (seenIds.has(job.external_id)) {
        throw new Error(`Duplicate external_id found: ${job.external_id}`);
      }
      seenIds.add(job.external_id);

      validatedQueue.push({
        external_id: job.external_id,
        job_url: job.job_url,
        title: job.title || null,
        company: job.company || null
      });
    }

    this.state = {
      status: 'idle',
      queue: validatedQueue,
      currentIndex: 0,
      extractedJobs: [],
      failed: [],
      batch_started_at: null,
      batch_finished_at: null,
      stopped_reason: null,
      last_successful_external_id: null
    };
  }

  start() {
    if (this.state.status === 'running') {
      return;
    }
    if (this.state.status === 'finished') {
      throw new Error("Batch already finished");
    }
    if (this.state.queue.length === 0) {
      throw new Error("Queue is empty");
    }
    this.state.status = 'running';
    if (!this.state.batch_started_at) {
      this.state.batch_started_at = new Date().toISOString();
    }
    this.state.stopped_reason = null;
  }

  stop(reason) {
    this.state.status = 'stopped';
    this.state.stopped_reason = reason;
  }

  cancel() {
    this.stop("cancelled_by_user");
  }

  getCurrentJob() {
    if (this.state.currentIndex >= this.state.queue.length) {
      return null;
    }
    return this.state.queue[this.state.currentIndex];
  }

  // normalize text for identity matching
  static normalizeIdentityText(text) {
    if (!text) return "";
    return text.toLowerCase().replace(/[^a-z0-9]/g, ' ').replace(/\s+/g, ' ').trim();
  }

  processExtraction(response) {
    if (this.state.status !== 'running') {
      throw new Error("Batch is not running");
    }

    const currentJob = this.getCurrentJob();
    if (!currentJob) {
      throw new Error("No current job to process");
    }

    if (!response || response.error) {
      throw new Error(response ? response.error : "Empty response from content script");
    }

    if (!response.jobs || response.jobs.length !== 1) {
      throw new Error(`Expected exactly 1 extracted job, got ${response.jobs ? response.jobs.length : 0}`);
    }

    const extractedJob = response.jobs[0];

    // Check external_id
    if (extractedJob.external_id !== currentJob.external_id) {
      throw new Error(`Extracted external_id (${extractedJob.external_id}) does not match expected (${currentJob.external_id})`);
    }

    // Check nonblank description
    if (!extractedJob.description || extractedJob.description.trim() === '') {
      throw new Error("Extracted description is empty");
    }

    // Identity match
    if (currentJob.title) {
      const qTitle = BatchOrchestrator.normalizeIdentityText(currentJob.title);
      const eTitle = BatchOrchestrator.normalizeIdentityText(extractedJob.title);
      if (qTitle && eTitle && qTitle !== eTitle) {
        throw new Error(`Title mismatch: expected '${currentJob.title}', got '${extractedJob.title}'`);
      }
    }
    if (currentJob.company) {
      const qComp = BatchOrchestrator.normalizeIdentityText(currentJob.company);
      const eComp = BatchOrchestrator.normalizeIdentityText(extractedJob.company);
      if (qComp && eComp && qComp !== eComp) {
        throw new Error(`Company mismatch: expected '${currentJob.company}', got '${extractedJob.company}'`);
      }
    }

    // Only copy allowed fields to ensure no DOM click or external leakage mutates things
    const safeJob = {
      external_id: extractedJob.external_id,
      title: extractedJob.title,
      company: extractedJob.company,
      location: extractedJob.location,
      remote_status: extractedJob.remote_status,
      salary: extractedJob.salary,
      employment_type: extractedJob.employment_type,
      job_url: extractedJob.job_url,
      description: extractedJob.description,
      date_found: extractedJob.date_found,
      application_status: "saved",
      source: "jobcopilot"
    };

    this.state.extractedJobs.push(safeJob);
    this.state.last_successful_external_id = currentJob.external_id;
    this.state.currentIndex++;

    if (this.state.currentIndex >= this.state.queue.length) {
      this.state.status = 'finished';
      this.state.batch_finished_at = new Date().toISOString();
    }
  }

  // Record the current job as failed and advance, so one bad/slow page does not
  // halt the whole run. The caller decides what counts as a failure (timeout,
  // empty description, identity mismatch, navigation error).
  skipCurrent(reason) {
    if (this.state.status !== 'running') return;
    const job = this.getCurrentJob();
    if (!job) return;
    if (!Array.isArray(this.state.failed)) this.state.failed = [];
    this.state.failed.push({ external_id: job.external_id, reason: reason });
    this.state.currentIndex++;
    if (this.state.currentIndex >= this.state.queue.length) {
      this.state.status = 'finished';
      this.state.batch_finished_at = new Date().toISOString();
    }
  }

  // One envelope per MAX_ENVELOPE_JOBS extracted jobs. Empty when nothing was extracted.
  generateExportPayloads(extensionVersion = "0.1.0") {
    const size = globalThis.ApplywrightExtension.MAX_ENVELOPE_JOBS;
    const jobs = this.state.extractedJobs;
    const payloads = [];
    for (let i = 0; i < jobs.length; i += size) {
      payloads.push(this.generateExportPayload(extensionVersion, jobs.slice(i, i + size)));
    }
    return payloads;
  }

  generateExportPayload(extensionVersion = "0.1.0", jobs = this.state.extractedJobs) {
    return {
      metadata: {
        source: 'jobcopilot',
        export_kind: 'batch_enrichment',
        exported_at: new Date().toISOString(),
        page_url: "https://app.jobcopilot.com/applications/review/*",
        detected_count: this.state.queue.length,
        exported_count: jobs.length,
        invalid_count: 0,
        duplicate_count: 0,
        warning_count: 0,
        warnings: [],
        extension_version: extensionVersion,
        
        batch_started_at: this.state.batch_started_at,
        batch_finished_at: this.state.batch_finished_at,
        requested_count: this.state.queue.length,
        succeeded_count: this.state.extractedJobs.length,
        failed_count: this.state.queue.length - this.state.extractedJobs.length,
        last_successful_external_id: this.state.last_successful_external_id,
        stopped_reason: this.state.stopped_reason
      },
      jobs: jobs,
      diagnostics: {
        status: this.state.status,
        currentIndex: this.state.currentIndex,
        failed: this.state.failed || []
      }
    };
  }
};
