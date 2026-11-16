export default {
  props: ["uploaderId", "pageId"],
  template: `
    <div v-show="dragging" class="record-component-drop-target" aria-hidden="true">
      <slot />
    </div>`,
  data() {
    return { dragging: false, hideTimer: null };
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
    this.hide();
  },
  methods: {
    isFileDrag(event) {
      return event.dataTransfer?.types.includes("Files");
    },
    isOverRecord(element) {
      return getHtmlElement(this.pageId)?.contains(element);
    },
    canAddFiles() {
      // NiceGUI's Upload wraps QUploader. Use its public addFiles API to
      // share the chooser's batch upload path and validation.
      return getElement(this.uploaderId)?.$refs.qRef?.canAddFiles;
    },
    hide() {
      clearTimeout(this.hideTimer);
      this.dragging = false;
    },
    onDragOver(event) {
      if (!this.isFileDrag(event)) return;
      event.preventDefault();
      if (!this.isOverRecord(event.target) || !this.canAddFiles()) {
        event.dataTransfer.dropEffect = "none";
        this.hide();
        return;
      }
      event.stopPropagation();
      event.dataTransfer.dropEffect = "copy";
      this.dragging = true;
      clearTimeout(this.hideTimer);
      // External drags may exit the browser without a final DOM event.
      this.hideTimer = setTimeout(this.hide, 900);
    },
    onDragLeave(event) {
      if (!this.isOverRecord(event.relatedTarget)) this.hide();
    },
    onDrop(event) {
      this.hide();
      if (!this.isFileDrag(event)) return;
      event.preventDefault();
      if (this.isOverRecord(event.target) && this.canAddFiles()) {
        event.stopPropagation();
        runMethod(this.uploaderId, "addFiles", [Array.from(event.dataTransfer.files)]);
      }
    },
  },
};
