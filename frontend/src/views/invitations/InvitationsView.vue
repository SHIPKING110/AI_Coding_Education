<script setup lang="ts">
import PageHead from '@/components/PageHead.vue'
import InvitationsPanel from './InvitationsPanel.vue'
</script>

<template>
  <div class="invitations">
    <PageHead
      title="招生邀约"
      eyebrow="INVITATIONS"
      sub="意向家长建档 · 聊天截图留存 · 体验课排课 · 到场转化一条龙"
    />
    <InvitationsPanel />
  </div>
</template>

<style scoped>
.invitations {
  position: relative;
}
</style>
