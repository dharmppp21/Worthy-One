import { useState } from "react";
import type { Runbook } from "../types";

interface RunbookPanelProps {
  runbooks: Runbook[];
  selectedService?: string;
  onCreate: (data: {
    tenant_id: string;
    service_name: string;
    title: string;
    description: string;
    steps: string[];
  }) => void;
  onDelete: (id: string) => void;
}

export function RunbookPanel({ runbooks, selectedService, onCreate, onDelete }: RunbookPanelProps) {
  const [isCreating, setIsCreating] = useState(false);
  const [formData, setFormData] = useState({
    tenant_id: "tenant-a",
    service_name: selectedService || "",
    title: "",
    description: "",
    steps: [""],
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onCreate({
      ...formData,
      steps: formData.steps.filter((s) => s.trim() !== ""),
    });
    setIsCreating(false);
    setFormData({
      tenant_id: "tenant-a",
      service_name: selectedService || "",
      title: "",
      description: "",
      steps: [""],
    });
  };

  const addStep = () => {
    setFormData((prev) => ({ ...prev, steps: [...prev.steps, ""] }));
  };

  const updateStep = (index: number, value: string) => {
    setFormData((prev) => {
      const newSteps = [...prev.steps];
      newSteps[index] = value;
      return { ...prev, steps: newSteps };
    });
  };

  const removeStep = (index: number) => {
    setFormData((prev) => {
      const newSteps = prev.steps.filter((_, i) => i !== index);
      if (newSteps.length === 0) newSteps.push("");
      return { ...prev, steps: newSteps };
    });
  };

  return (
    <div className="runbook-panel">
      <div className="runbook-header">
        <h2 className="runbook-title">📖 Runbooks</h2>
        <button className="create-runbook-btn" onClick={() => setIsCreating(!isCreating)}>
          {isCreating ? "Cancel" : "+ New Runbook"}
        </button>
      </div>

      {isCreating && (
        <form className="runbook-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Service Name</label>
            <input
              type="text"
              value={formData.service_name}
              onChange={(e) => setFormData((prev) => ({ ...prev, service_name: e.target.value }))}
              required
            />
          </div>
          <div className="form-group">
            <label>Title</label>
            <input
              type="text"
              value={formData.title}
              onChange={(e) => setFormData((prev) => ({ ...prev, title: e.target.value }))}
              required
            />
          </div>
          <div className="form-group">
            <label>Description</label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData((prev) => ({ ...prev, description: e.target.value }))}
              required
              rows={3}
            />
          </div>
          <div className="form-group">
            <label>Steps</label>
            {formData.steps.map((step, i) => (
              <div key={i} className="step-input-row">
                <input
                  type="text"
                  value={step}
                  onChange={(e) => updateStep(i, e.target.value)}
                  placeholder={`Step ${i + 1}`}
                />
                <button type="button" className="remove-step-btn" onClick={() => removeStep(i)}>
                  ✕
                </button>
              </div>
            ))}
            <button type="button" className="add-step-btn" onClick={addStep}>
              + Add Step
            </button>
          </div>
          <button type="submit" className="submit-runbook-btn">
            Save Runbook
          </button>
        </form>
      )}

      {runbooks.length === 0 ? (
        <div className="runbook-empty">
          <p>No runbooks yet.</p>
          <p className="runbook-hint">Create a runbook to capture operational procedures for a service.</p>
        </div>
      ) : (
        <div className="runbook-list">
          {runbooks.map((runbook) => (
            <div key={runbook.id} className="runbook-card">
              <div className="runbook-card-header">
                <h3>{runbook.title}</h3>
                <span className="service-tag">{runbook.service_name}</span>
              </div>
              <p className="runbook-description">{runbook.description}</p>
              {runbook.steps.length > 0 && (
                <ol className="runbook-steps">
                  {runbook.steps.map((step, i) => (
                    <li key={i}>{step}</li>
                  ))}
                </ol>
              )}
              <div className="runbook-footer">
                <span className="runbook-time">{new Date(runbook.created_at).toLocaleDateString()}</span>
                <button className="delete-runbook-btn" onClick={() => onDelete(runbook.id)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
