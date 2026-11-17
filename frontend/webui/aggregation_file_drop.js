export default {
  props: ["pageId", "uploadUrl", "enabled", "physical"],
  template: `<div v-show="dragging" class="record-component-drop-target">
    <div v-if="physical"><slot name="physical" /></div>
    <div v-else-if="fileCount <= 1"><slot name="single" /></div>
    <div v-else><slot name="multiple" /></div>
  </div>`,
  data() {
    return { dragging: false, fileCount: 0, hideTimer: null, pendingFiles: null };
  },
  mounted() {
    document.addEventListener("dragenter", this.onDragOver, true);
    document.addEventListener("dragover", this.onDragOver, true);
    document.addEventListener("dragleave", this.onDragLeave);
    document.addEventListener("drop", this.onDrop, true);
    document.addEventListener("dragend", this.hide);
  },
  beforeUnmount() {
    document.removeEventListener("dragenter", this.onDragOver, true);
    document.removeEventListener("dragover", this.onDragOver, true);
    document.removeEventListener("dragleave", this.onDragLeave);
    document.removeEventListener("drop", this.onDrop, true);
    document.removeEventListener("dragend", this.hide);
    this.clear();
  },
  methods: {
    isFileDrag(event) { return event.dataTransfer?.types.includes("Files"); },
    isOverPage(element) { return getHtmlElement(this.pageId)?.contains(element); },
    hide() { clearTimeout(this.hideTimer); this.dragging = false; },
    clear() { this.hide(); this.pendingFiles = null; },
    onDragOver(event) {
      if (!this.isFileDrag(event)) return;
      event.preventDefault();
      if (!this.isOverPage(event.target) || this.pendingFiles || (!this.enabled && !this.physical)) {
        event.dataTransfer.dropEffect = "none";
        this.hide();
        return;
      }
      event.stopPropagation();
      event.dataTransfer.dropEffect = this.physical ? "none" : "copy";
      this.fileCount = Array.from(event.dataTransfer.items || []).filter(item => item.kind === "file").length;
      this.dragging = true;
      clearTimeout(this.hideTimer);
      this.hideTimer = setTimeout(this.hide, 900);
    },
    onDragLeave(event) { if (!this.isOverPage(event.relatedTarget)) this.hide(); },
    onDrop(event) {
      this.hide();
      if (!this.isFileDrag(event)) return;
      event.preventDefault();
      if (!this.isOverPage(event.target)) return;
      event.stopPropagation();
      if (this.physical || !this.enabled || this.pendingFiles) return;
      const files = Array.from(event.dataTransfer.files);
      const target = event.target.closest("[data-drop-mode]");
      if (!files.length || !target || !this.$el.contains(target)) return;
      const mode = target.dataset.dropMode;
      if (files.length > 1 && mode === "single") return;
      this.pendingFiles = files;
      this.$emit("files-dropped", { count: files.length, separate: mode !== "combined", filenames: files.map(file => file.name) });
    },
    async upload() {
      if (!this.pendingFiles) return;
      const form = new FormData();
      // Unique form fields preserve duplicate filenames and the complete drop
      // order through NiceGUI's multi-upload route (which uses form.values()).
      this.pendingFiles.forEach((file, index) => form.append(`file-${index}`, file, file.name));
      try {
        const response = await fetch((window.path_prefix || "") + this.uploadUrl, { method: "POST", body: form });
        if (!response.ok) throw new Error("Upload failed");
      } catch (_) {
        this.$emit("upload-failed");
      }
    },
  },
};
