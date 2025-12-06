# Page snapshot

```yaml
- main [ref=e2]:
  - generic [ref=e11]:
    - img "Form logo" [ref=e14]
    - generic [ref=e16]:
      - heading "Sign in" [level=2] [ref=e18]
      - paragraph [ref=e20]: Sign in to your account.
    - form "primary-form" [ref=e25]:
      - generic [ref=e26]:
        - generic [ref=e28]:
          - generic [ref=e29]: Email address
          - textbox "Email address" [active] [ref=e34]:
            - /placeholder: name@host.com
        - generic [ref=e36]:
          - generic [ref=e37]: Password
          - textbox "Password" [ref=e42]:
            - /placeholder: Enter password
          - generic [ref=e44]:
            - generic:
              - generic [ref=e47]:
                - generic [ref=e48]:
                  - img [ref=e49]
                  - checkbox "Show password" [ref=e51]
                - generic [ref=e53]: Show password
              - link "Forgot your password?" [ref=e56]:
                - /url: /forgotPassword?client_id=3218p1roiidl8jfudr3uqv4dvb&redirect_uri=http%3A%2F%2Flocalhost%3A5173&response_type=code&scope=email+openid+profile
        - generic [ref=e58]:
          - button "Sign in" [ref=e60] [cursor=pointer]
          - paragraph [ref=e63]:
            - text: New user?
            - link "Create an account" [ref=e64]:
              - /url: /signup?client_id=3218p1roiidl8jfudr3uqv4dvb&redirect_uri=http%3A%2F%2Flocalhost%3A5173&response_type=code&scope=email+openid+profile
```