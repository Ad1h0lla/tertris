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

  // ─── Connectors ───────────────────────────────────────────────────────────────

  async getConnectors(userId = 'user_001') {
    return this.request(`/credentials/${userId}`, 'GET');
  }

  async connectApp(appName, credential, connectionType = 'api_key', displayName = null, userId = 'user_001') {
    if (!credential || credential.startsWith('mock_')) {
      throw new Error('connectApp: real credential required — do not pass mock tokens');
    }
    return this.request('/credentials/connect', 'POST', {
      app_name: appName,
      credential,
      connection_type: connectionType,
      display_name: displayName,
      user_id: userId,
    });
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
}

export const api = new ApiClient();
