import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export const useProjectStore = create(
  persist(
    (set, get) => ({
      // Core State
      project: null,           // Current project metadata ({ id: executionId, name, createdAt })
      jamSession: {
        messages: [],
        coverage: {},
        isActive: false,
      },
      understanding: null,     // Formulated goal and requirements from backend
      workflow: [],            // List of phase objects defining execution order (N phases)
      phases: {},              // phaseId -> phase execution data (status, outcome, etc.)
      agents: {},              // agentId -> agent status, logs, outputs, chat
      currentPhaseId: null,    // Currently active phase in the workflow
      connectors: [],          // Connected apps for this project
      bots: [],                // Continuous running bots
      health: null,            // Post-launch metrics

      // Actions
      setProject: (project) => set({ project }),

      // Jam Session Actions
      startJamSession: (initialMessage) => set((state) => ({
        jamSession: {
          messages: [{ role: 'agent', content: initialMessage, ts: Date.now() }],
          coverage: {},
          isActive: true,
        },
        understanding: null,
        workflow: [],
        phases: {},
        agents: {},
        currentPhaseId: null,
      })),
      addJamMessage: (message) => set((state) => ({
        jamSession: {
          ...state.jamSession,
          messages: [...state.jamSession.messages, message],
        }
      })),
      setJamCoverage: (coverage) => set((state) => ({
        jamSession: { ...state.jamSession, coverage }
      })),
      endJamSession: () => set((state) => ({
        jamSession: { ...state.jamSession, isActive: false }
      })),

      // Understanding Actions
      setUnderstanding: (understanding) => set({ understanding }),

      // Workflow Actions
      setWorkflow: (workflow) => set({ workflow }),
      setCurrentPhaseId: (phaseId) => set({ currentPhaseId: phaseId }),
      syncExecutionState: (statusData) => set((state) => {
        if (!statusData) return {};
        const backendWorkflow = statusData.workflow || [];
        const updatedPhases = { ...state.phases };

        backendWorkflow.forEach((ph) => {
          updatedPhases[ph.id] = {
            ...(updatedPhases[ph.id] || {}),
            status: ph.status,
            agent: ph.agent,
            outcome: ph.output?.outcome,
            validation: ph.output?.review_result,
            runner_result: ph.output?.verification_result,
          };
        });

        return {
          workflow: backendWorkflow,
          currentPhaseId: statusData.current_phase || state.currentPhaseId,
          phases: updatedPhases,
        };
      }),

      // Phase & Agent Actions
      updatePhase: (phaseId, updates) => set((state) => ({
        phases: {
          ...state.phases,
          [phaseId]: { ...(state.phases[phaseId] || {}), ...updates },
        }
      })),
      updateAgent: (agentId, updates) => set((state) => ({
        agents: {
          ...state.agents,
          [agentId]: { ...(state.agents[agentId] || {}), ...updates },
        }
      })),
      addAgentLog: (agentId, logMessage) => set((state) => {
        const agent = state.agents[agentId] || { logs: [] };
        return {
          agents: {
            ...state.agents,
            [agentId]: { ...agent, logs: [...(agent.logs || []), logMessage] }
          }
        };
      }),

      // Connections and Bots
      setConnectors: (connectors) => set({ connectors }),
      setBots: (bots) => set({ bots }),
      setHealth: (health) => set({ health }),

      // Reset entirely
      reset: () => set({
        project: null,
        jamSession: { messages: [], coverage: {}, isActive: false },
        understanding: null,
        workflow: [],
        phases: {},
        agents: {},
        currentPhaseId: null,
        connectors: [],
        bots: [],
        health: null,
      })
    }),
    {
      name: 'tetris_project_store', // localStorage key
    }
  )
);
