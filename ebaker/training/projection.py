import torch
import math
import torch.nn as nn
import logging


# def get_projection_head(input_dim, args):
#     if args.projection_n_layers==0:
#         return nn.Sequential(nn.Linear(input_dim, args.projection_dim)).to(args.device)
#     else:
#         layers = [
#             nn.Linear(input_dim, args.projection_hidden_dim),
#             nn.BatchNorm1d(args.projection_hidden_dim),
#             nn.ReLU(inplace=False)]
#         for i in range(args.projection_n_layers-1):
#             layers.extend([
#                 nn.Linear(args.projection_hidden_dim, args.projection_hidden_dim),
#                 nn.BatchNorm1d(args.projection_hidden_dim), 
#                 nn.ReLU(inplace=False)])
#         layers.append(nn.Linear(args.projection_hidden_dim, args.projection_dim))
#         return nn.Sequential(*layers).to(args.device)

class SkipConnection(nn.Module):
    def __init__(self) -> None:
        super().__init__()
    
    def forward(self, input, output):
        return input + output

class DINOHead(nn.Module):
    def __init__(self, in_dim, out_dim, weight_norm_=True, act='gelu', use_bn=False, nlayers=3, hidden_dim=2048, bottleneck_dim=256, skip_last_layer=False, residual=False):
        super().__init__()

        if nlayers == 0:
            self.mlp = nn.Identity()
            bottleneck_dim = in_dim
        elif nlayers == 1:
            self.mlp = nn.Linear(in_dim, bottleneck_dim)
        else:
            layers = [nn.Linear(in_dim, hidden_dim)]
            if use_bn:
                layers.append(nn.BatchNorm1d(hidden_dim))
            if act == 'gelu':
                layers.append(nn.GELU())
            elif act == 'relu':
                layers.append(nn.ReLU(inplace=True))
            for _ in range(nlayers - 2):
                layers.append(nn.Linear(hidden_dim, hidden_dim))
                if use_bn:
                    layers.append(nn.BatchNorm1d(hidden_dim))
                if act == 'gelu':
                    layers.append(nn.GELU())
                elif act == 'relu':
                    layers.append(nn.ReLU(inplace=True))
            layers.append(nn.Linear(hidden_dim, bottleneck_dim))
            self.mlp = nn.Sequential(*layers)
        self.apply(self._init_weights)

        if not skip_last_layer:
            if weight_norm_:
                self.last_layer = nn.utils.weight_norm(nn.Linear(bottleneck_dim, out_dim, bias=False))
                self.last_layer.weight_g.data.fill_(1)
                self.last_layer.weight_g.requires_grad = False
            else:
                self.last_layer = nn.Linear(bottleneck_dim, out_dim, bias=False)
        else:
            self.last_layer = nn.Identity()

    def _init_weights(self, m):
        if isinstance(m, nn.Linear):
            trunc_normal_(m.weight, std=.02)
            if isinstance(m, nn.Linear) and m.bias is not None:
                nn.init.constant_(m.bias, 0)

    def forward(self, x, skip_last_layer=False):
        x = self.mlp(x)
        x = nn.functional.normalize(x, dim=-1, p=2)
        if not skip_last_layer:
            x = self.last_layer(x)
        return x


def _no_grad_trunc_normal_(tensor, mean, std, a, b):
    # Cut & paste from PyTorch official master until it's in a few official releases - RW
    # Method based on https://people.sc.fsu.edu/~jburkardt/presentations/truncated_normal.pdf
    def norm_cdf(x):
        # Computes standard normal cumulative distribution function
        return (1. + math.erf(x / math.sqrt(2.))) / 2.

    if (mean < a - 2 * std) or (mean > b + 2 * std):
        logging.warning("mean is more than 2 std from [a, b] in nn.init.trunc_normal_. "
                      "The distribution of values may be incorrect.",
                      stacklevel=2)

    with torch.no_grad():
        # Values are generated by using a truncated uniform distribution and
        # then using the inverse CDF for the normal distribution.
        # Get upper and lower cdf values
        l = norm_cdf((a - mean) / std)
        u = norm_cdf((b - mean) / std)

        # Uniformly fill tensor with values from [l, u], then translate to
        # [2l-1, 2u-1].
        tensor.uniform_(2 * l - 1, 2 * u - 1)

        # Use inverse cdf transform for normal distribution to get truncated
        # standard normal
        tensor.erfinv_()

        # Transform to proper mean, std
        tensor.mul_(std * math.sqrt(2.))
        tensor.add_(mean)

        # Clamp to ensure it's in the proper range
        tensor.clamp_(min=a, max=b)
        return tensor


def trunc_normal_(tensor, mean=0., std=1., a=-2., b=2.):
    return _no_grad_trunc_normal_(tensor, mean, std, a, b)