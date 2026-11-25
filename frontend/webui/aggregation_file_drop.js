export default {
  props: ["pageId", "uploadUrl", "enabled", "physical", "collection"],
  template: `<div v-show="dragging" class="record-component-drop-target">
    <div v-if="physical"><slot name="physical" /></div>
    <div v-else-if="collection || fileCount <= 1"><slot name="single" /></div>
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
    acceptsDrag(event) {
      if (!event.dataTransfer?.types.includes("Files")) return false;
      // Dialog uploaders own drops on their files area, including a draft
      // opened from an aggregation. Leave their native events untouched.
      if (event.target.closest(".q-dialog") || document.querySelector(".q-dialog[role=dialog]")) return false;
      return !this.collection || this.isOverPage(event.target);
    },
    isOverPage(element) { return getHtmlElement(this.pageId)?.contains(element); },
    dropMode(element, fileCount) {
      if (this.collection || fileCount === 1) return "single";
      const target = element.closest('[data-drop-mode="separate"], [data-drop-mode="combined"]');
      return target && this.$el.contains(target) ? target.dataset.dropMode : null;
    },
    hide() { clearTimeout(this.hideTimer); this.dragging = false; },
    clear() { this.hide(); this.pendingFiles = null; },
    onDragOver(event) {
      if (!this.acceptsDrag(event)) return;
      event.preventDefault();
      if (!this.isOverPage(event.target) || this.pendingFiles || (!this.enabled && !this.physical)) {
        event.dataTransfer.dropEffect = "none";
        this.hide();
        return;
      }
      event.stopPropagation();
      this.fileCount = Array.from(event.dataTransfer.items || []).filter(item => item.kind === "file").length;
      const mode = this.dropMode(event.target, this.fileCount || 1);
      event.dataTransfer.dropEffect = !this.physical && mode ? "copy" : "none";
      this.dragging = true;
      clearTimeout(this.hideTimer);
      this.hideTimer = setTimeout(this.hide, 900);
    },
    onDragLeave(event) { if (!this.isOverPage(event.relatedTarget)) this.hide(); },
    onDrop(event) {
      this.hide();
      if (!this.acceptsDrag(event)) return;
      event.preventDefault();
      if (!this.isOverPage(event.target)) return;
      event.stopPropagation();
      if (this.physical || !this.enabled || this.pendingFiles) return;
      const files = Array.from(event.dataTransfer.files);
      if (!files.length) return;
      const mode = this.dropMode(event.target, files.length);
      if (!mode) return;
      this.pendingFiles = files;
      if (this.collection) {
        this.$emit("files-dropped", { files: files.map(({name, size, type}) => ({name, size, type})) });
        return;
      }
      this.$emit("files-dropped", { count: files.length, separate: mode !== "combined", filenames: files.map(file => file.name) });
    },
    async transfer(index, url) {
      const file = this.pendingFiles?.[index];
      if (!file) return false;
      const form = new FormData();
      form.append("file", file, file.name);
      try {
        const response = await fetch((window.path_prefix || "") + url, {method: "POST", body: form});
        return response.ok;
      } catch (_) { return false; }
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
