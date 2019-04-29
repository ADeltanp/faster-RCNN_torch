import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import cupy as cp
from Models.utils.ProposalLayer import ProposalLayer
from Models.utils.boundingbox import generate_anchor_base, all_anchors


class RPN(nn.Module):
    def __init__(self, RPN, extractor, img_size, img_scale,
                 init_mean=0, init_std=0.01, cp_enable=False):
        super(RPN, self).__init__()
        self.extractor = extractor
        self.img_size = img_size
        self.img_scale = img_scale
        self.cp_enable = cp_enable
        self.anchor_base = generate_anchor_base(cp_enable=self.cp_enable)
        if extractor is "VGG16":
            self.feat_receptive_len = 16

        self.share = nn.Sequential(
            nn.Conv2d(512, 512, 3, padding=1),
            nn.ReLU()
        )
        self.cls = nn.Conv2d(512, 18, 1, padding=0)
        self.reg = nn.Conv2d(512, 36, 1, padding=0)
        self.ProposalLayer = ProposalLayer(self.extractor)
        self._initialize_params(init_mean, init_std)

    def forward(self, x, img_size, img_scale=1.0, phase='test'):
        # cupy compatible TODO Compatibility Not Tested
        if self.cp_enable:
            xp = cp
        else:
            xp = np
        bat, _, h, w = x.shape
        anchors = all_anchors(self.anchor_base, self.feat_receptive_len, h, w, phase=phase)
        num_anchors = anchors[0]

        shared = self.share(x)
        cls = self.cls(shared)
        cls = cls.permute(0, 2, 3, 1).contiguous().view(bat, h, w, num_anchors, 2)  # shape (B, h, w, n_a, 2)
        cls = F.softmax(cls, dim=4)
        cls = cls.view(bat, -1, 2)

        reg = self.reg(shared)
        reg = reg.permute(0, 2, 3, 1).contiguous().view(bat, -1, 4)  # shape (B, h * w * n_a, 4)

        # roi is not encoded tuple (not t_x, t_y, ... but x_min, x_max, ...)
        roi_list = list()
        roi_id = list()
        for i in range(bat):
            roi = self.ProposalLayer(
                cls[i].cpu().data.numpy(),
                reg[i].cpu().data.numpy(),
                anchors,
                img_size,
                img_scale,
                phase
            )
            batch_id = i * xp.ones((len(roi),), dtype=xp.int32)
            roi_list.append(roi)
            roi_id.append(batch_id)

        xp.concatenate(roi_list, axis=0)
        roi_id = xp.concatenate(roi_id, axis=0)

        return reg, cls, roi_list, roi_id, anchors

    def _initialize_params(self, mean, std):
        self.share[0].weight.data.normal_(mean, std)
        self.cls.weight.data.normal_(mean, std)
        self.reg.weight.data.normal_(mean, std)

