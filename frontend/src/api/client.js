/**
 * Tetris API Client
 *
 * Contract (verified against live OpenAPI spec at http://localhost:8001):
 *
 *   GET  /endpoint          → normal fetch, no body
 *   POST /endpoint          → JSON body with Content-Type: application/json
 */

const API_BASE = 'http://localhost:8000';

// ─── Error class ──────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(endpoint, status, statusText, body) {
    const detail = body?.detail
      ? (Array.isArray(body.detail)
          ? body.detail.map(d => `[${d.loc?.join('.')}] ${d.msg}`).join('; ')
          : String(body.detail))
      : statusText;

    super(`${status} ${statusText} — ${endpoint} — ${detail}`);
    this.endpoint   = endpoint;
    this.status     = status;
    this.statusText = statusText;
    this.body       = body;
    this.detail     = detail;
  }
}

// ─── Core client ──────────────────────────────────────────────────────────────

class ApiClient {
  /**
   * Low-level request handler.
   */
  async request(endpoint, method = 'GET', payload = null) {
    const url = `${API_BASE}${endpoint}`;

    const options = {
      method,
      headers: {
        'Content-Type': 'application/json',
      },
    };

    if (method !== 'GET' && payload !== null) {
      options.body = JSON.stringify(payload);
    }

    const response = await fetch(url, options);

    let body = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }

    if (!response.ok) {
      throw new ApiError(endpoint, response.status, response.statusText, body);
    }

    return body;
  }

  // ─── Health ─────────────────────────────────────────────────────────────────

  async checkHealth() {
    try {
      const data = await this.request('/', 'GET');
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message };
    }
  }

  // ─── Intake / Jam Session ────────────────────────────────────────────────────

  async intake(idea, conversationHistory = [], userId = 'user_001') {
    return this.request('/intake', 'POST', {
      idea,
      conversation_history: conversationHistory,
      user_id: userId,
    });
  }

  async intakeReply(message, history = [], goal = {}, userId = 'user_001') {
    return this.request('/intake/reply', 'POST', {
      message,
      history,
      goal,
      user_id: userId,
    });
  }

  // ─── Execution ───────────────────────────────────────────────────────────────

  async execute(confirmedGoal, phase = 1, reviewMode = 'auto', userId = 'user_001') {
    return this.request('/execute', 'POST', {
      confirmed: true,
      confirmed_goal: confirmedGoal,
      phase,
      review_mode: reviewMode,
      user_id: userId,
    });
  }

  async executeAgent(confirmedGoal, phaseNumber = 1, agentType = 'code', context = '', executionId = null, feedback = null, userId = 'user_001') {
    return this.request('/execute/agent', 'POST', {
      confirmed_goal: confirmedGoal,
      phase: phaseNumber,
      agent_type: agentType,
      context,
      execution_id: executionId,
      feedback,
      user_id: userId,
    });
  }

  async validatePhase(confirmedGoal, phase1Output, userId = 'user_001') {
    return this.request('/execute/validate', 'POST', {
      confirmed_goal: confirmedGoal,
      phase1_output: phase1Output,
      user_id: userId,
    });
  }

  async simulate(confirmedGoal, planOutput, codeOutput, userId = 'user_001') {
    return this.request('/execute/simulate', 'POST', {
      confirmed_goal: confirmedGoal,
      plan_output: planOutput,
      code_output: codeOutput,
      user_id: userId,
    });
  }

  async marketExecute(channel, content, target, credentialKey = '', userId = 'user_001') {
    return this.request('/execute/market', 'POST', {
      channel,
      content,
      target,
      credential_key: credentialKey,
      user_id: userId,
    });
  }

  async approve(executionId, approved = true, feedback = '', phase = null, userId = 'user_001') {
    return this.request('/approve', 'POST', {
      execution_id: executionId,
      approved,
      feedback,
      phase,
      user_id: userId,
    });
  }

  async nextPhase(confirmedGoal, phase = 1, reviewMode = 'auto', userId = 'user_001') {
    return this.request('/next-phase', 'POST', {
      confirmed_goal: confirmedGoal,
      phase,
      review_mode: reviewMode,
      user_id: userId,
    });
  }

  // ─── Connectors (M3.5-A) ─────────────────────────────────────────────────────

  /**
   * List all active credential records for a user.
   * Returns metadata only — no raw secrets.
   */
  async getConnectors(userId = 'user_001') {
    return this.request(`/credentials/${userId}`, 'GET');
  }

  /**
   * Store structured credentials for a platform.
   *
   * @param {string}  appName      - e.g. 'reddit', 'twitter', 'linkedin', 'sendgrid', 'smtp'
   * @param {object}  credentials  - structured key→value dict matching the platform schema
   * @param {string}  [connectionType]
   * @param {string}  [displayName]
   * @param {string}  [userId]
   */
  async connectApp(appName, credentials, connectionType = 'api_key', displayName = null, userId = 'user_001') {
    // Guard: credentials must be a non-empty object
    if (!credentials || typeof credentials !== 'object' || Array.isArray(credentials)) {
      throw new Error('connectApp: credentials must be a non-empty object');
    }
    return this.request('/credentials/connect', 'POST', {
      app_name:        appName,
      credentials,
      connection_type: connectionType,
      display_name:    displayName,
      user_id:         userId,
    });
  }

  /**
   * Soft-delete (deactivate) a stored credential.
   */
  async disconnectApp(appName, userId = 'user_001') {
    return this.request(`/credentials/${userId}/${appName}`, 'DELETE');
  }

  /**
   * Live-verify stored credentials for a platform without performing any write action.
   * Returns { status, verified, display_name, error }.
   */
  async testConnector(appName, userId = 'user_001') {
    return this.request(`/credentials/test/${appName}?user_id=${userId}`, 'POST');
  }

  /**
   * Fetch connected/verified readiness for all distribution platforms.
   * Used by the Distribution Orchestrator to gate campaign execution.
   */
  async getReadiness(userId = 'user_001') {
    return this.request(`/credentials/readiness/${userId}`, 'GET');
  }

  // ─── Bots ─────────────────────────────────────────────────────────────────────

  async createBots(confirmedGoal, campaignOutput, planOutput, botTypes, websiteUrl = '', userId = 'user_001') {
    return this.request('/bots/create', 'POST', {
      confirmed_goal: confirmedGoal,
      campaign_output: campaignOutput,
      plan_output: planOutput,
      bot_types: botTypes,
      website_url: websiteUrl,
      user_id: userId,
    });
  }

  async getUserBots(userId = 'user_001') {
    return this.request(`/bots/${userId}`, 'GET');
  }

  // ─── Executions ───────────────────────────────────────────────────────────────

  async getExecutions(userId = 'user_001') {
    return this.request(`/executions/${userId}`, 'GET');
  }

  async getExecutionPhases(executionId, userId = 'user_001') {
    return this.request(`/executions/${userId}/${executionId}/phases`, 'GET');
  }

  async getExecutionStatus(executionId, userId = 'user_001') {
    return this.request(`/executions/${userId}/${executionId}/status`, 'GET');
  }

  // ─── Projects ───────────────────────────────────────────────────────────────

  async getProjects() {
    return this.request('/api/projects', 'GET');
  }

  // ─── Distribution Campaigns (M3.5-B) ─────────────────────────────────────────

  async createDistributionCampaign(executionId, userId = 'user_001', distributionPlan = null, actions = null) {
    return this.request('/distribution/campaigns', 'POST', {
      execution_id: executionId,
      user_id: userId,
      distribution_plan: distributionPlan,
      actions: actions,
    });
  }

  async getDistributionCampaign(campaignId) {
    return this.request(`/distribution/campaigns/${campaignId}`, 'GET');
  }

  async checkCampaignReadiness(campaignId, userId = 'user_001') {
    return this.request(`/distribution/campaigns/${campaignId}/check-readiness?user_id=${userId}`, 'POST');
  }

  async approveCampaignActions(campaignId, actionIds = null, approveAll = false, userId = 'user_001') {
    return this.request(`/distribution/campaigns/${campaignId}/approve`, 'POST', {
      user_id: userId,
      action_ids: actionIds,
      approve_all: approveAll,
    });
  }

  async executeCampaign(campaignId, userId = 'user_001', actionIds = null) {
    return this.request(`/distribution/campaigns/${campaignId}/execute`, 'POST', {
      user_id: userId,
      action_ids: actionIds,
    });
  }

  async retryCampaign(campaignId, userId = 'user_001', actionIds = null) {
    return this.request(`/distribution/campaigns/${campaignId}/retry`, 'POST', {
      user_id: userId,
      action_ids: actionIds,
    });
  }

  // ─── Workforce Engine (Stage 7B) ─────────────────────────────────────────────

  async executeWorkforce({ executionId, phaseId = null, workflowType = null, userId = 'user_001', approvedTaskIds = null, dryRun = false }) {
    return this.request('/api/workforce/execute', 'POST', {
      execution_id: executionId,
      phase_id: phaseId,
      workflow_type: workflowType,
      user_id: userId,
      approved_task_ids: approvedTaskIds,
      dry_run: dryRun,
    });
  }

  async getWorkforceStatus(executionId) {
    return this.request(`/api/workforce/${executionId}/status`, 'GET');
  }

  async approveWorkforceTask(executionId, taskId, feedback = null, userId = 'user_001') {
    return this.request(`/api/workforce/${executionId}/tasks/${taskId}/approve`, 'POST', {
      user_id: userId,
      feedback: feedback,
    });
  }

  async getWorkforceHealth(executionId) {
    return this.request(`/api/workforce/${executionId}/health`, 'GET');
  }

  async assessWorkforceHealth(executionId, targetUrl = null, responseTimeThresholdMs = 500.0, userId = 'user_001') {
    return this.request(`/api/workforce/${executionId}/health`, 'POST', {
      user_id: userId,
      target_url: targetUrl,
      response_time_threshold_ms: responseTimeThresholdMs,
    });
  }
}

export const api = new ApiClient();

