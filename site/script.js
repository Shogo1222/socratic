const copyButtons = document.querySelectorAll("[data-copy]");

for (const button of copyButtons) {
  button.addEventListener("click", async () => {
    const command = button.dataset.copy;
    if (!command) return;

    try {
      await navigator.clipboard.writeText(command);
      button.textContent = "COPIED";
      button.classList.add("copied");
      window.setTimeout(() => {
        button.textContent = "COPY";
        button.classList.remove("copied");
      }, 1800);
    } catch {
      button.textContent = "SELECT";
      const code = button.previousElementSibling;
      const selection = window.getSelection();
      const range = document.createRange();
      if (selection && code) {
        range.selectNodeContents(code);
        selection.removeAllRanges();
        selection.addRange(range);
      }
    }
  });
}
