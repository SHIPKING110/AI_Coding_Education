import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import autogrow from './directives/autogrow'
import router from './router'

const app = createApp(App)
app.directive('autogrow', autogrow)
app.use(createPinia()).use(router).mount('#app')