import { useState } from "react";
import { generateIaC } from "../services/api";

function IaCGenerator() {
  const [input, setInput] = useState({ provider: "AWS", type: "t3.medium" });
  const [script, setScript] = useState("");

  const handleChange = (e) =>
    setInput({ ...input, [e.target.name]: e.target.value });

  const handleSubmit = async (e) => {
    e.preventDefault();
    const res = await generateIaC(input);
    setScript(res.data.iac);
  };

  return (
    <div>
      <h3>Terraform Script Generator</h3>
      <form onSubmit={handleSubmit}>
        <label>Instance Type</label>
        <input
          type="text"
          name="type"
          value={input.type}
          onChange={handleChange}
        />
        <button type="submit">Generate</button>
      </form>
      <textarea value={script} readOnly rows={10} cols={60} />
    </div>
  );
}

export default IaCGenerator;
