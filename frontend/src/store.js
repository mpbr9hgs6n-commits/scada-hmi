import { defineStore } from 'pinia'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    user: JSON.parse(localStorage.getItem('user') || 'null'),
    mustChangePwd: localStorage.getItem('must_change_pwd') === '1'
  }),
  actions: {
    setLogin(token, user, must) {
      this.token = token
      this.user = user
      this.mustChangePwd = !!must
      localStorage.setItem('token', token)
      localStorage.setItem('user', JSON.stringify(user))
      localStorage.setItem('must_change_pwd', must ? '1' : '0')
    },
    clearMustChange() {
      this.mustChangePwd = false
      localStorage.setItem('must_change_pwd', '0')
    },
    logout() {
      this.token = ''
      this.user = null
      this.mustChangePwd = false
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      localStorage.removeItem('must_change_pwd')
    }
  }
})
