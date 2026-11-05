<script setup lang="ts">
import AppSidebar from './components/AppSidebar.vue'
</script>

<template>
  <div class="app">
    <AppSidebar />
    <main class="main">
      <router-view />
    </main>
  </div>
</template>
